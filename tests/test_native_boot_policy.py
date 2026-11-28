"""Exercise the actual menu policy in an isolated boot directory."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/p16-boot-menu-policy'
SPEC = importlib.util.spec_from_file_location('boot_verify', SOURCE.with_name('verify-boot.py'))
BOOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOT)


class BootPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.boot = self.root / 'boot'
        images = self.boot / 'EFI/Linux'
        images.mkdir(parents=True)
        self.primary = images / 'omarchy_p16.efi'
        self.recovery = images / 'omarchy_p16-recovery.efi'
        for image in (self.primary, self.recovery):
            image.write_bytes(image.name.encode())
        self.config = self.boot / 'limine.conf'
        self.config.write_text('default_entry: Omarchy-P16\ntimeout: 5\nquiet: no\n' +
                               self.entry('Omarchy-P16', self.primary) +
                               self.entry('Omarchy-P16-Recovery', self.recovery) +
                               '/Windows\n path: boot():/EFI/Microsoft/Boot/bootmgfw.efi\n')
        self.script = SOURCE.read_text().replace('[[ $EUID == 0 ]] || exit 1', 'true')
        self.script = self.script.replace('/run/lock/boot-partition.lock', str(self.root / 'lock'))
        self.script = self.script.replace('/boot', str(self.boot))

    def entry(self, title, image):
        return (f'/{title}\n protocol: efi\n path: boot():/EFI/Linux/{image.name}#' +
                hashlib.blake2b(image.read_bytes()).hexdigest() + '\n')

    def run_policy(self):
        return subprocess.run(['bash', '-c', self.script], text=True, capture_output=True)

    def test_valid_menu_is_preserved(self):
        original = self.config.read_bytes()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_bytes(), original)
        with patch.object(BOOT, 'verify_image') as verify:
            BOOT.verify_menu(self.config, self.boot)
            self.assertEqual([x.args for x in verify.call_args_list], [(self.primary,), (self.recovery,)])

    def test_official_indented_os_group_and_snapshot_menu_are_preserved(self):
        selected = self.entry('/linux-p16-platform-36', self.primary)
        self.config.write_text(
            'default_entry: Omarchy/linux-p16-platform-36\ntimeout: 5\nquiet: no\n'
            '/+Omarchy\n comment: machine-id=test-machine\n' +
            '\n'.join('  '+line for line in selected.split('\n') if line) +
            '\n  //Snapshots\n' + self.entry('Omarchy-P16-Recovery', self.recovery))
        self.script = self.script.replace('/usr/bin/p16-platform-update-check', '/usr/bin/true')
        before = self.config.read_bytes()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_bytes(), before)
        with patch.object(BOOT, 'verify_image') as verify:
            BOOT.verify_menu(self.config, self.boot)
            self.assertEqual([call.args for call in verify.call_args_list],
                             [(self.primary,), (self.recovery,)])

    def test_corrupt_primary_selects_recovery_and_reports_failure(self):
        self.primary.write_bytes(b'damaged')
        result = self.run_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('default_entry: Omarchy-P16-Recovery\n', self.config.read_text())
        self.assertIn('/Windows\n', self.config.read_text())

    def test_nondefault_entry_with_stale_root_override_is_rejected(self):
        cmdline = 'root=/dev/mapper/root rootflags=subvol=/@candidate ro'
        original = self.config.read_text()
        entry = '/+Omarchy\n' + self.entry('/linux-p16-platform-omarchy', self.primary)
        with patch.object(BOOT, 'sections', return_value={'.cmdline': cmdline.encode()}), \
                patch.object(BOOT, 'verify_image'):
            for override in ('root=/dev/mapper/root rootflags=subvol=@old ro',
                             'root=/dev/wrong rootflags=subvol=@candidate ro',
                             'root=/dev/mapper/root ro',
                             cmdline + ' rootflags=subvolid=256',
                             cmdline + '\n kernel_cmdline: ' + cmdline):
                with self.subTest(override=override):
                    self.config.write_text(original + entry + f' cmdline: {override}\n')
                    with self.assertRaisesRegex(ValueError, 'Limine .*Omarchy/linux-p16-platform-omarchy'):
                        BOOT.verify_menu(self.config, self.boot)
            for option in ('', ' kernel_cmdline: ' + cmdline.replace('/@candidate', '@candidate') + '\n'):
                self.config.write_text(original + entry + option)
                BOOT.verify_menu(self.config, self.boot)

    def test_no_valid_image_preserves_menu(self):
        for image in (self.primary, self.recovery):
            image.unlink()
        original = self.config.read_bytes()
        self.assertNotEqual(self.run_policy().returncode, 0)
        self.assertEqual(self.config.read_bytes(), original)

    def test_missing_and_duplicate_selected_entry_are_rejected(self):
        original = self.config.read_text()
        for text in (original.replace('/Omarchy-P16\n', '/Other\n'),
                     original + self.entry('Omarchy-P16', self.primary)):
            self.config.write_text(text)
            self.assertNotEqual(self.run_policy().returncode, 0)
            self.assertEqual(self.config.read_text(), text)

    def test_unmanaged_default_is_preserved(self):
        self.config.write_text(self.config.read_text().replace('default_entry: Omarchy-P16', 'default_entry: Windows'))
        original = self.config.read_bytes()
        self.assertEqual(self.run_policy().returncode, 0)
        self.assertEqual(self.config.read_bytes(), original)

    def test_hash_syntax_and_path_escape_are_rejected(self):
        original = self.config.read_text()
        pin = hashlib.blake2b(self.primary.read_bytes()).hexdigest()
        for text in (original.replace('#' + pin, ''), original.replace(pin, 'x' * 128),
                     original.replace('/EFI/Linux/omarchy_p16.efi', '/EFI/Linux/../../escape.efi')):
            self.config.write_text(text)
            self.assertNotEqual(self.run_policy().returncode, 0)
            self.assertEqual(self.config.read_text(), text)
            with patch.object(BOOT, 'verify_image'), self.assertRaises(ValueError):
                BOOT.verify_menu(self.config, self.boot)

    def test_corrupt_recovery_does_not_displace_valid_default(self):
        self.recovery.write_bytes(b'damaged')
        self.assertNotEqual(self.run_policy().returncode, 0)
        self.assertIn('default_entry: Omarchy-P16\n', self.config.read_text())

    def test_unqualified_managed_kernel_falls_back(self):
        self.config.write_text(self.config.read_text().replace('default_entry: Omarchy-P16\n',
                              'default_entry: Omarchy/linux-p16-platform\n') +
                              '/Omarchy\n' + self.entry('/linux-p16-platform', self.primary))
        self.script = self.script.replace('/usr/bin/p16-platform-update-check', '/bin/false')
        self.assertNotEqual(self.run_policy().returncode, 0)
        self.assertIn('default_entry: Omarchy-P16-Recovery\n', self.config.read_text())


if __name__ == '__main__':
    unittest.main()
