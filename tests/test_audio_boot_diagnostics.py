"""Keep early diagnostics from changing encryption, ACPI or DSP boot policy."""
import importlib.util
from pathlib import Path
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('audio_diagnostics', ROOT/'scripts/stage-audio-boot-diagnostics.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
BASE = 'cryptdevice=PARTUUID=example:root root=/dev/mapper/root acpi_osi="!Windows 2022" acpi=nospcr n1x_adsp.auto_boot=1'


class AudioBootDiagnosticsTests(unittest.TestCase):
    def test_linux_double_quoted_osi_and_hardware_policy_survive(self):
        output = stage.diagnostic_cmdline(BASE+' quiet splash loglevel=4')
        self.assertIn('acpi_osi="!Windows 2022"', output)
        self.assertIn('n1x_adsp.auto_boot=1', shlex.split(output))
        self.assertNotIn('quiet', shlex.split(output))
        self.assertNotIn('splash', shlex.split(output))

    def test_diagnostic_keys_have_one_value_even_after_repeated_staging(self):
        output = stage.diagnostic_cmdline(stage.diagnostic_cmdline(BASE+' loglevel=4 earlycon=pl011 panic=30'))
        for expected in stage.DIAGNOSTICS:
            key=expected.split('=',1)[0]
            self.assertEqual([arg for arg in shlex.split(output) if arg.split('=',1)[0] == key], [expected])

    def test_refuses_to_drop_non_debug_efi_policy(self):
        with self.assertRaisesRegex(ValueError, 'EFI policy'):
            stage.diagnostic_cmdline(BASE+' efi=noruntime')

    def test_requires_the_existing_n1x_acpi_console_quirks(self):
        with self.assertRaises(ValueError):
            stage.diagnostic_cmdline('root=/dev/example')


if __name__ == '__main__':
    unittest.main()
