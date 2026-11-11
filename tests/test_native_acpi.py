"""Stage native-ACPI images without changing live images or relaxing legacy checks."""
import hashlib
import gzip
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fixtures import entry, fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_acpi_stage', ROOT / 'scripts/stage-native-acpi.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
policy = stage.POLICY
REFERENCE = b'synthetic reference SSDT'


def archive(records):
    parents = {p.as_posix() for name, body in records for p in Path(name).parents if str(p) != '.'}
    data = b''
    for parent in sorted(parents, key=lambda name: (name.count('/'), name)):
        record = bytearray(entry(parent.encode()))
        record[14:22] = b'000041ed'  # Directory, 0755.
        data += record
    data += b''.join(entry(name.encode(), body) for name, body in records)
    data += entry(b'TRAILER!!!')
    return data + bytes(-len(data) % 512)


class ACPIPolicyTests(unittest.TestCase):
    def setUp(self):
        pin = patch.object(policy, 'REFERENCE_SHA256', hashlib.sha256(REFERENCE).hexdigest())
        pin.start()
        self.addCleanup(pin.stop)

    def test_removal_preserves_every_other_record_and_the_main_payload(self):
        first = archive([('early/firmware/microcode', b'keep first')])
        second = archive([(policy.REFERENCE_SSDT, REFERENCE), ('other', b'keep second')])
        main = b'\x28\xb5\x2f\xfdcompressed-main-payload\0\xff'
        original = first + second + main
        modified = policy.without_reference_ssdt(original)
        before, tail = policy.early_archives(original)
        after, new_tail = policy.early_archives(modified)
        self.assertEqual(new_tail, main)
        self.assertEqual(tail, new_tail)
        self.assertEqual([r for a in after for r in a],
                         [r for a in before for r in a if r[0] != policy.REFERENCE_SSDT])

    def test_unknown_missing_duplicate_and_dsdt_overrides_are_not_removed(self):
        for records in ([], [(policy.REFERENCE_SSDT, b'unknown')],
                        [('kernel/firmware/acpi/DSDT.aml', b'dsdt')],
                        [(policy.REFERENCE_SSDT, REFERENCE)] * 2,
                        [(policy.REFERENCE_SSDT, REFERENCE), ('kernel/firmware/acpi/SSDT2.aml', b'other')]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                policy.without_reference_ssdt(archive(records))

    def test_truncated_and_unsafe_cpio_is_rejected(self):
        valid = archive([(policy.REFERENCE_SSDT, REFERENCE)])
        for data in (valid[:20], valid[:115], valid[:145],
                     valid[:6] + b'xxxxxxxx' + valid[14:],
                     archive([('../kernel/firmware/acpi/SSDT.aml', REFERENCE)])):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                policy.without_reference_ssdt(data)

    def test_explicit_profiles_reject_the_other_profile_and_unknown_tables(self):
        self.assertEqual(policy.check_files({}, 'native'), 'native')
        self.assertEqual(policy.check_files({}, 'auto'), 'native')
        legacy = {policy.REFERENCE_SSDT: REFERENCE}
        self.assertEqual(policy.check_files(legacy, 'legacy'), 'legacy')
        self.assertEqual(policy.check_files(legacy, 'auto'), 'legacy')
        for files, mode in (({}, 'legacy'), (legacy, 'native'),
                            ({policy.REFERENCE_SSDT: b'unknown'}, 'auto'),
                            ({'kernel/firmware/acpi/DSDT.aml': b'x'}, 'native')):
            with self.subTest(mode=mode, files=files), self.assertRaises(ValueError):
                policy.check_files(files, mode)

    def test_extracted_tree_checks_include_nested_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            acpi = root / policy.ACPI_DIR
            acpi.mkdir(parents=True)
            self.assertEqual(policy.check_tree(root, 'native'), 'native')
            (acpi / 'SSDT.aml').write_bytes(REFERENCE)
            self.assertEqual(policy.check_tree(root, 'legacy'), 'legacy')
            nested = acpi / 'nested'
            nested.mkdir()
            (nested / 'other.aml').write_bytes(b'unknown')
            with self.assertRaises(ValueError):
                policy.check_tree(root, 'auto')
            (nested / 'other.aml').unlink()
            nested.rmdir()
            (acpi / 'SSDT.aml').unlink()
            acpi.rmdir()
            acpi.symlink_to(root / 'outside', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                policy.check_tree(root, 'native')


class NativeStageTests(unittest.TestCase):
    def test_signed_and_pcr_signed_inputs_are_rejected(self):
        raw, _, _ = fixture()
        stage.require_unsigned(raw, {})
        signed = bytearray(raw)
        pe = struct.unpack_from('<I', signed, 60)[0]
        struct.pack_into('<II', signed, pe + 24 + 112 + 4 * 8, len(signed), 16)
        with self.assertRaisesRegex(ValueError, 'Signed UKI'):
            stage.require_unsigned(signed, {})
        with self.assertRaisesRegex(ValueError, 'PCR-signed'):
            stage.require_unsigned(raw, {'.pcrsig': b'signed policy'})

    def test_default_source_requires_the_pinned_selected_image(self):
        with tempfile.TemporaryDirectory() as directory:
            boot = Path(directory)
            image = boot / 'EFI/Linux/source.efi'
            image.parent.mkdir(parents=True)
            image.write_bytes(b'fixture')
            pin = hashlib.blake2b(image.read_bytes()).hexdigest()
            menu = boot / 'limine.conf'
            menu.write_text('default_entry: Omarchy/test\n/Omarchy\n//test\n'
                            f' protocol: efi\n path: boot():/EFI/Linux/source.efi#{pin}\n')
            self.assertEqual(stage.default_image(menu, boot), image)
            image.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                stage.default_image(menu, boot)

    @unittest.skipUnless(Path('/usr/lib/systemd/boot/efi/linuxaa64.efi.stub').exists()
                         and shutil.which('objcopy'), 'ARM64 systemd stub and objcopy required')
    def test_real_pe_rewrite_preserves_other_payloads_and_does_not_overwrite(self):
        stub = Path('/usr/lib/systemd/boot/efi/linuxaa64.efi.stub')
        raw = stub.read_bytes()
        stage.require_unsigned(raw, {})
        pe = struct.unpack_from('<I', raw, 60)[0]
        image_base = struct.unpack_from('<Q', raw, pe + 24 + 24)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source.efi', root / 'candidate'
            original_initrd = archive([(policy.REFERENCE_SSDT, REFERENCE), ('early-other', b'keep')])
            original_initrd += b'\x1f\x8bmain-payload-unchanged'
            payloads = {'.linux': b'kernel payload', '.initrd': original_initrd,
                        '.uname': b'7.2.8-test\0', '.cmdline': b'preserve existing arguments\0'}
            command = ['objcopy']
            for index, (name, data) in enumerate(payloads.items()):
                file = root / name[1:]
                file.write_bytes(data)
                command += ['--add-section', name + '=' + str(file),
                            '--change-section-vma', name + '=' + hex(image_base + 0x200000 + index * 0x100000),
                            '--set-section-flags', name + '=alloc,load,readonly,data']
            subprocess.run(command + [str(stub), str(source)], check=True, capture_output=True)
            source_bytes = source.read_bytes()
            with patch.object(policy, 'REFERENCE_SHA256', hashlib.sha256(REFERENCE).hexdigest()), \
                 patch.object(stage.BOOT, 'verify_image') as verify:
                report = stage.stage(source, output)
                self.assertEqual([call.kwargs['acpi_mode'] for call in verify.call_args_list],
                                 ['legacy', 'native'])
                self.assertEqual(source.read_bytes(), source_bytes)
                self.assertFalse(report['installed'])
                self.assertFalse(report['boot_files_written'])
                self.assertFalse(report['hardware_qualified'])
                after = stage.BOOT.sections(output / 'native-acpi.efi')
                before = stage.BOOT.sections(source)
                for name, data in before.items():
                    if name != '.initrd':
                        self.assertEqual(after[name], data, name)
                self.assertEqual(policy.early_archives(after['.initrd'])[1],
                                 policy.early_archives(original_initrd)[1])
                with self.assertRaisesRegex(ValueError, 'new staging directory'):
                    stage.stage(source, output)
            failed = root / 'failed'
            with patch.object(policy, 'REFERENCE_SHA256', hashlib.sha256(REFERENCE).hexdigest()), \
                 patch.object(stage.BOOT, 'verify_image', side_effect=[None, ValueError('native verification failed')]):
                with self.assertRaisesRegex(ValueError, 'native verification failed'):
                    stage.stage(source, failed)
                self.assertFalse(failed.exists())
                self.assertEqual(source.read_bytes(), source_bytes)


class BootProfileVerificationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('lsinitcpio'), 'lsinitcpio required')
    def test_native_image_needs_no_override_allocator_but_legacy_stays_strict(self):
        boot = stage.BOOT
        release = '7.2.8-fixture'
        names = ('nvidia.ko', 'nvidia-drm.ko', 'hid-asus.ko', 'spi-hid-acpi.ko',
                 'i2c-mt65xx.ko', 'i2c-hid-acpi.ko')
        main = gzip.compress(archive([(f'usr/lib/modules/{release}/{name}', b'fixture') for name in names]))
        real_check_output = subprocess.check_output
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / 'modules' / release
            (modules / 'build').mkdir(parents=True)
            (modules / 'build/.config').write_text('\n'.join([
                'CONFIG_ACPI_WMI=m', 'CONFIG_ASUS_WMI=m', 'CONFIG_ASUS_NB_WMI=m',
                'CONFIG_SPI_HID_ACPI=m']))
            (modules / 'vmlinuz').write_bytes(b'kernel')
            fake_module = modules / 'fixture.ko'
            fake_module.write_bytes(b'fixture')
            sections = {'.uname': release.encode() + b'\0', '.linux': b'kernel', '.initrd': main,
                        '.cmdline': b'acpi_osi="!Windows 2022" console=tty0 acpi=nospcr\0'}

            def mapped(path):
                return root / 'modules' if str(path) == '/usr/lib/modules' else Path(path)

            def command(args, **kwargs):
                if args[0] == 'pacman':
                    return 'linux-p16-platform\n'
                if args[0] == 'modprobe':
                    return 'insmod ' + str(fake_module) + '\n'
                if args[0] == 'modinfo':
                    return release + ' SMP\n'
                return real_check_output(args, **kwargs)

            with patch.object(boot, 'sections', return_value=sections), \
                 patch.object(boot, 'Path', side_effect=mapped), \
                 patch.object(boot.subprocess, 'check_output', side_effect=command), \
                 patch.object(policy, 'REFERENCE_SHA256', hashlib.sha256(REFERENCE).hexdigest()):
                boot.verify_image(root / 'image.efi', acpi_mode='native')
                original_command = sections['.cmdline']
                sections['.cmdline'] = original_command.rstrip(b'\0') + b' acpi=off\0'
                with self.assertRaisesRegex(ValueError, 'ACPI-Deaktivierung'):
                    boot.verify_image(root / 'image.efi', acpi_mode='native')
                sections['.cmdline'] = original_command
                with self.assertRaisesRegex(ValueError, 'exact reference SSDT'):
                    boot.verify_image(root / 'image.efi')
                sections['.initrd'] = archive([(policy.REFERENCE_SSDT, REFERENCE)]) + main
                with self.assertRaisesRegex(ValueError, 'contains an override'):
                    boot.verify_image(root / 'image.efi', acpi_mode='native')
                (modules / 'build/System.map').write_text('')
                with self.assertRaisesRegex(ValueError, 'Allocator'):
                    boot.verify_image(root / 'image.efi', acpi_mode='legacy')
