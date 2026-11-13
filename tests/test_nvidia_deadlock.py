"""Cover the observed DRM master-drop failure using the actual patched function."""
from pathlib import Path
import subprocess
import unittest


class NvidiaDeadlockTests(unittest.TestCase):
    def test_atomic_colorspace_deadlock_and_cleanup(self):
        root = Path(__file__).resolve().parents[1]
        subprocess.run(['python3', str(root / 'platform/nvidia/test_deadlock.py')],
                       check=True, timeout=40)
