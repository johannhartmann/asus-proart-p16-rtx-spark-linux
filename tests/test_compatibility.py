"""Compatibility follows actual inputs; BIOS labels are not an eligibility API."""
import contextlib
import hashlib
import io
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_installation import module


ROOT = Path(__file__).resolve().parents[1]
peripherals = module('compatibility_peripherals', 'peripherals.py')
acpi = module('compatibility_acpi', '../acpi/acpi_builder.py')


class ShellHostChecks(unittest.TestCase):
    def run_check(self, check, architecture='aarch64', vendor='ASUS',
                  product='ProArt P16 H7607BA'):
        # Only the documented board fields exist. A BIOS read would fail.
        script = '''
source "$1/scripts/common.sh"
uname() { printf '%s\\n' "$task_architecture"; }
cat() {
  case "$1" in
    /sys/class/dmi/id/sys_vendor) printf '%s\\n' "$task_vendor" ;;
    /sys/class/dmi/id/product_name) printf '%s\\n' "$task_product" ;;
    *) echo "Unexpected host read: $1" >&2; return 73 ;;
  esac
}
task_architecture=$2 task_vendor=$3 task_product=$4
"$5"
'''
        return subprocess.run(['bash', '-c', script, 'host-check', str(ROOT),
                               architecture, vendor, product, check],
                              capture_output=True, text=True)

    def test_source_builds_only_require_the_target_architecture(self):
        result = self.run_check('check_arch', vendor='Other', product='Other')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_board_policy_does_not_read_a_bios_label(self):
        result = self.run_check('check_model')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_architecture_and_board_remain_rejected(self):
        for options in ({'architecture': 'x86_64'}, {'vendor': 'Other'},
                        {'product': 'Other P16'}):
            with self.subTest(options=options):
                result = self.run_check('check_model', **options)
                self.assertNotEqual(result.returncode, 0)


class PeripheralCompatibilityTests(unittest.TestCase):
    def test_unknown_or_absent_bios_label_does_not_skip_firmware_hash_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dmi, firmware = root / 'dmi', root / 'firmware'
            dmi.mkdir()
            firmware.mkdir()
            (dmi / 'sys_vendor').write_text('ASUS\n')
            (dmi / 'product_name').write_text('ProArt P16 H7607BA\n')
            rows = []
            for name in peripherals.FIRMWARE_NAMES:
                data = name.encode()
                (firmware / name).write_bytes(data)
                rows.append({'name': name, 'bytes': len(data),
                             'sha256': hashlib.sha256(data).hexdigest()})
            quirks = root / 'touchpad.quirks'
            quirks.write_bytes((ROOT / 'config/p16-touchpad.quirks').read_bytes())
            board_check = peripherals.check_machine
            with patch.object(peripherals.platform, 'machine', return_value='aarch64'), \
                 patch.object(peripherals, 'check_machine', side_effect=lambda: board_check(dmi)), \
                 patch.object(peripherals, 'FIRMWARE_DIR', firmware), \
                 patch.object(peripherals, 'QUIRKS', quirks), \
                 patch.object(peripherals, 'INITCPIO', root / 'absent-initcpio.conf'), \
                 patch.object(peripherals, 'manifest', return_value={'files': rows}), \
                 contextlib.redirect_stdout(io.StringIO()):
                for version in ('H7607BA.300', 'H7607BA.303', 'H7607BA.305', 'future', None):
                    if version is None:
                        (dmi / 'bios_version').unlink()
                    else:
                        (dmi / 'bios_version').write_text(version)
                    with self.subTest(version=version):
                        peripherals.check_installed()
                (firmware / rows[-1]['name']).write_bytes(b'corrupt firmware')
                with self.assertRaisesRegex(ValueError, 'Size/SHA-256 mismatch'):
                    peripherals.check_installed()

    def test_board_and_architecture_still_scope_the_file_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            dmi = Path(directory)
            (dmi / 'sys_vendor').write_text('ASUS')
            (dmi / 'product_name').write_text('ProArt P16 H7607BA')
            with patch.object(peripherals.platform, 'machine', return_value='x86_64'):
                with self.assertRaisesRegex(ValueError, 'AArch64 required'):
                    peripherals.check_machine(dmi)
            with patch.object(peripherals.platform, 'machine', return_value='aarch64'):
                (dmi / 'product_name').write_text('Other P16')
                with self.assertRaisesRegex(ValueError, 'product_name'):
                    peripherals.check_machine(dmi)


class ACPIInputCompatibilityTests(unittest.TestCase):
    def test_unknown_table_layout_stops_before_transform_compile_or_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump, output = root / 'dump', root / 'output'
            dump.mkdir()
            table = bytearray(36)
            table[:4] = b'SSDT'
            table[10:24] = acpi.ASUS_SSDT
            struct.pack_into('<I', table, 4, len(table))
            table[9] = -sum(table) % 256
            (dump / 'DSDT').write_bytes(table)
            with patch.object(acpi, 'splice_ssdt') as transform, \
                 patch.object(acpi, 'check_iasl') as compile_check, \
                 patch.object(acpi, 'publish') as publish:
                with self.assertRaisesRegex(ValueError, 'unsupported ASUS SSDT input layout'):
                    acpi.build(dump, repo=output)
                transform.assert_not_called()
                compile_check.assert_not_called()
                publish.assert_not_called()
                self.assertFalse(output.exists())
