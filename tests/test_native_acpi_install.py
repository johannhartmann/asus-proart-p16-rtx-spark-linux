"""Install a test entry without changing the selected boot or recovery image."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_acpi_install', ROOT / 'scripts/install-native-acpi-test.py')
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


class NativeACPIInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.boot, self.candidate = root / 'boot', root / 'candidate'
        images = self.boot / 'EFI/Linux'
        images.mkdir(parents=True)
        self.candidate.mkdir()
        self.source = images / 'working.efi'
        self.source.write_bytes(b'working legacy image')
        self.recovery = images / 'recovery.efi'
        self.recovery.write_bytes(b'preserved recovery image')
        self.image = self.candidate / 'native-acpi.efi'
        self.image.write_bytes(b'native image')
        self.menu = self.boot / 'limine.conf'
        text = 'default_entry: Omarchy-P16\nquiet: no\ntimeout: 5\n'
        for title, path in [('Omarchy-P16', self.source), ('Omarchy-P16-Recovery', self.recovery)]:
            text += (f'/{title}\n protocol: efi\n path: boot():/EFI/Linux/{path.name}#'
                     + hashlib.blake2b(path.read_bytes()).hexdigest() + '\n')
        self.menu.write_text(text)
        self.original = self.menu.read_bytes()
        (self.candidate / 'manifest.json').write_text(json.dumps({
            'candidate_sha256': INSTALL.STAGE.digest(self.image.read_bytes()),
            'source_sha256': INSTALL.STAGE.digest(self.source.read_bytes()),
            'source_kernel': 'test-kernel'}))
        self.command = b'acpi_osi="!Windows 2022" console=tty0 acpi=nospcr\0'

    def sections(self, path):
        return {'.linux': b'unchanged kernel', '.cmdline': self.command,
                '.initrd': b'legacy initrd' if path == self.source else b'native initrd'}

    def run_install(self):
        with patch.object(INSTALL.STAGE.BOOT, 'sections', side_effect=self.sections), \
             patch.object(INSTALL.STAGE.BOOT, 'verify_image'), \
             patch.object(INSTALL.STAGE, 'require_unsigned'), \
             patch.object(INSTALL.STAGE, 'section_layout', return_value={}), \
             patch.object(INSTALL.STAGE.POLICY, 'without_reference_ssdt', return_value=b'native initrd'):
            return INSTALL.install(self.candidate, self.boot)

    def test_install_preserves_default_recovery_and_original_menu_bytes(self):
        report = self.run_install()
        self.assertFalse(report['default_changed'])
        self.assertFalse(report['hardware_qualified'])
        self.assertTrue(self.menu.read_bytes().startswith(self.original))
        self.assertEqual(Path(report['menu_backup']).read_bytes(), self.original)
        self.assertEqual(self.source.read_bytes(), b'working legacy image')
        self.assertEqual(self.recovery.read_bytes(), b'preserved recovery image')
        self.assertEqual(Path(report['image']).read_bytes(), self.image.read_bytes())
        self.assertEqual(INSTALL.STAGE.default_image(self.menu, self.boot), self.source)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.run_install()

    def test_changed_candidate_source_or_dsp_autostart_never_changes_boot(self):
        for change in ('candidate', 'source', 'dsp'):
            with self.subTest(change=change):
                self.image.write_bytes(b'native image')
                self.source.write_bytes(b'working legacy image')
                self.command = b'console=tty0\0'
                if change == 'dsp':
                    self.command = b'n1x_adsp.auto_boot=1 console=tty0\0'
                else:
                    (self.image if change == 'candidate' else self.source).write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    self.run_install()
                self.assertEqual(self.menu.read_bytes(), self.original)
                self.assertFalse((self.boot / 'EFI/Linux' / INSTALL.IMAGE).exists())
                self.assertFalse(list(self.boot.glob('limine.conf.before-*')))

    def test_failed_final_menu_verification_keeps_original_and_removes_new_image(self):
        real_verify = INSTALL.STAGE.BOOT.verify_menu
        calls = 0

        def verify(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('injected menu verification failure')
            return real_verify(*args, **kwargs)

        with patch.object(INSTALL.STAGE.BOOT, 'verify_menu', side_effect=verify):
            with self.assertRaisesRegex(ValueError, 'injected'):
                self.run_install()
        self.assertEqual(self.menu.read_bytes(), self.original)
        self.assertFalse((self.boot / 'EFI/Linux' / INSTALL.IMAGE).exists())


if __name__ == '__main__':
    unittest.main()
