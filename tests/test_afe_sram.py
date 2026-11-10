"""Check SRAM lease behavior and exact integration into the packaged AFE driver."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AFESRAMTests(unittest.TestCase):
    def test_native_irq_cache_and_power_loss(self):
        subprocess.run(['python3', str(ROOT / 'platform/dsp/afe/test_irq_cache.py')],
                       check=True, timeout=40)

    def test_asoc_card_and_retained_sleep(self):
        for name in ('test_card.py', 'test_pm.py'):
            subprocess.run(['python3', str(ROOT / 'platform/dsp/afe' / name)],
                           check=True, timeout=40)

    def test_dsp_frontend_producer_period_and_close_lifetime(self):
        subprocess.run(['python3', str(ROOT / 'platform/dsp/afe/test_frontend.py')],
                       check=True, timeout=40)

    def test_lifetimes_faults_and_concurrent_leases(self):
        subprocess.run(['python3', str(ROOT / 'platform/dsp/afe/test_sram.py')],
                       check=True, timeout=40)

    def test_packaged_patch_reproduces_canonical_owner_and_pm_integration(self):
        spec = importlib.util.spec_from_file_location('afe_patch', ROOT / 'scripts/prepare-afe-sram-patch.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        before, after = module.sources(ROOT / 'kernel/src/linux-7.2.8')
        with tempfile.TemporaryDirectory(prefix='afe-sram-replay-') as directory:
            directory = Path(directory)
            for name, source in before.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)
            result = subprocess.run(['patch', '-p1', '--fuzz=0', '--batch',
                                     '-i', str(ROOT / 'kernel/p16-afe-sram.patch')],
                                    cwd=directory, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name, expected in after.items():
                self.assertEqual((directory / name).read_text(), expected, name)


if __name__ == '__main__':
    unittest.main()
