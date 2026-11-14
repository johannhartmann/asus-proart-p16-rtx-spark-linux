"""Firmware-backed devices must not be published from protected early images."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fixtures import fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('late_install', ROOT / 'scripts/boot_audit.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ProviderImageAuditTests(unittest.TestCase):
    def test_audits_renamed_primary_recovery_and_managed_images(self):
        with tempfile.TemporaryDirectory() as directory:
            boot = Path(directory)
            images = boot / 'EFI/Linux'
            images.mkdir(parents=True)
            data, _, _ = fixture()
            for name in ('omarchy_p16.efi', 'omarchy_p16-recovery.efi', 'omarchy_linux-p16-platform.efi'):
                (images / name).write_bytes(data)
            with patch.object(installer.subprocess, 'check_output', return_value='usr/lib/modules/test/driver.ko\n') as listing:
                checked = installer.npu_initramfs_audit(boot)
                self.assertEqual(set(checked), {str(p) for p in images.iterdir()})
                self.assertEqual(listing.call_count, 3)

    def test_rejects_embedded_npu_in_any_image(self):
        with tempfile.TemporaryDirectory() as directory:
            boot = Path(directory)
            images = boot / 'EFI/Linux'
            images.mkdir(parents=True)
            data, _, _ = fixture()
            (images / 'omarchy_p16-recovery.efi').write_bytes(data)
            with patch.object(installer.subprocess, 'check_output',
                              return_value='usr/lib/modules/test/n1x_npu_bootstrap.ko.zst\n'):
                with self.assertRaisesRegex(RuntimeError, 'embedded'):
                    installer.npu_initramfs_audit(boot)

    def test_rejects_missing_images(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, 'No Linux UKIs'):
                installer.npu_initramfs_audit(Path(directory))


if __name__ == '__main__':
    unittest.main()
