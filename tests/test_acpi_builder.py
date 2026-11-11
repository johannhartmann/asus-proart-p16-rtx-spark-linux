"""The power package builds only its pinned SSDT, never a DSDT or combined CPIO."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('power_ssdt_builder', ROOT / 'acpi/acpi_builder.py')
ACPI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACPI)


def ssdt():
    data = bytearray(36)
    data[:4] = b'SSDT'
    struct.pack_into('<I', data, 4, len(data))
    data[10:24] = ACPI.ASUS_SSDT
    data[9] = -sum(data) % 256
    return bytes(data)


class PowerSSDTBuildTests(unittest.TestCase):
    def test_only_ssdt_is_needed_and_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump, output = root / 'dump', root / 'output'
            dump.mkdir()
            source = ssdt()
            (dump / 'SSDT2').write_bytes(source)
            # Neither a missing nor an unrelated/broken DSDT can gate this build.
            for dsdt in (None, b'DSDT unrelated boot-dependent data'):
                if dsdt is not None:
                    (dump / 'DSDT').write_bytes(dsdt)

                def compile_ssdt(compiler, arguments, work):
                    self.assertEqual(arguments, ['-p', 'power', 'power.dsl'])
                    (work / 'power.aml').write_bytes(b'compiled methods')

                with patch.object(ACPI, 'SSDT_INPUT', hashlib.sha256(source).hexdigest()), \
                     patch.object(ACPI, 'check_iasl', return_value='/pinned/iasl'), \
                     patch.object(ACPI, 'derive_asl', return_value=b'verified ASL'), \
                     patch.object(ACPI, 'run_iasl', side_effect=compile_ssdt), \
                     patch.object(ACPI, 'splice_ssdt', return_value=b'verified SSDT'):
                    report = ACPI.build(dump, repo=output)
                self.assertEqual(report['dump'], {'SSDT': 'SSDT2'})
                self.assertEqual(set(report['overrides']), {'SSDT.aml'})
                self.assertEqual(set(report['outputs']),
                                 {ACPI.SSDT_PATH, ACPI.ASL_PATH, ACPI.OVERRIDE_PATH})
                self.assertEqual((output / ACPI.OVERRIDE_PATH).read_bytes(), b'verified SSDT')
                self.assertFalse(list(output.rglob('DSDT*')))
                self.assertFalse(list(output.rglob('*.cpio')))

    def test_ambiguous_or_absent_asus_ssdt_stops_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory)
            with patch.object(ACPI, 'check_iasl') as compiler:
                with self.assertRaisesRegex(ValueError, 'No ASUS SSDT'):
                    ACPI.build(dump)
                first = ssdt()
                second = bytearray(first)
                second[8] = 1
                second[9] = 0
                second[9] = -sum(second) % 256
                (dump / 'SSDT1').write_bytes(first)
                (dump / 'SSDT2').write_bytes(second)
                with self.assertRaisesRegex(ValueError, 'Different ASUS SSDT'):
                    ACPI.build(dump)
                compiler.assert_not_called()


if __name__ == '__main__':
    unittest.main()
