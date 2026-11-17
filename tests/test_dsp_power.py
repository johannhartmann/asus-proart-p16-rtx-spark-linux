"""Keep the actual packaged SSPM/checked-shutdown regression in the main suite."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DSPPowerTests(unittest.TestCase):
    def test_packaged_normal_and_checked_power_paths(self):
        subprocess.run(['python3', str(ROOT/'platform/dsp/test_power.py')],
                       check=True, timeout=40)
