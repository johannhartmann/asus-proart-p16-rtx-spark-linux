#!/usr/bin/env python3
"""Run the real shell helper with mocked console commands, never a real VT."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class VTTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nvidia-vt-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'params').write_text('UseKernelSuspendNotifiers: 1\n')
        (self.root/'vt').write_text('1\n')
        for name, code in {
            'fgconsole': 'cat "$MOCK_VT_ROOT/vt"',
            'chvt': '''printf 'switch %s\n' "$1" >> "$MOCK_VT_ROOT/log"
if [[ -e $MOCK_VT_ROOT/fail ]]; then exit 1; fi
printf '%s\n' "$1" > "$MOCK_VT_ROOT/vt"''',
        }.items():
            path = self.root/name
            path.write_text('#!/bin/bash\nset -eu\n'+code+'\n')
            path.chmod(0o700)
        source = (HERE/'nvidia-notifier-vt').read_text()
        # Only the private test copy substitutes root/path/console OS edges.
        guard = "[[ $EUID == 0 ]] || { echo 'VT handoff requires root' >&2; exit 1; }"
        assert source.count(guard) == 1
        source = source.replace(guard, ': # private fixture is unprivileged')
        source = source.replace('export PATH=/usr/bin:/bin',
                                f'export PATH={self.root}:/usr/bin:/bin')
        source = source.replace('/run/nvidia-notifier-vt/console', str(self.root/'console'))
        source = source.replace('/proc/driver/nvidia/params', str(self.root/'params'))
        self.script = self.root/'helper'
        self.script.write_text(source)
        self.script.chmod(0o700)
        self.env = dict(os.environ, MOCK_VT_ROOT=str(self.root))

    def run_helper(self, action):
        return subprocess.run([str(self.script), action], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_roundtrip_and_idempotent_restore(self):
        self.assertEqual(self.run_helper('prepare').returncode, 0)
        self.assertEqual((self.root/'console').read_text(), '1\n')
        self.assertEqual((self.root/'console').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root/'vt').read_text(), '63\n')
        self.assertEqual(self.run_helper('restore').returncode, 0)
        self.assertEqual((self.root/'vt').read_text(), '1\n')
        self.assertEqual(self.run_helper('restore').returncode, 0)
        self.assertEqual((self.root/'log').read_text(), 'switch 63\nswitch 1\n')

    def test_failed_prepare_unwinds_saved_state(self):
        (self.root/'fail').touch()
        self.assertNotEqual(self.run_helper('prepare').returncode, 0)
        self.assertTrue((self.root/'console').exists())
        (self.root/'fail').unlink()
        self.assertEqual(self.run_helper('restore').returncode, 0)
        self.assertFalse((self.root/'console').exists())

    def test_manual_console_change_is_respected(self):
        self.assertEqual(self.run_helper('prepare').returncode, 0)
        (self.root/'vt').write_text('2\n')
        self.assertEqual(self.run_helper('restore').returncode, 0)
        self.assertEqual((self.root/'vt').read_text(), '2\n')

    def test_disabled_notifiers_do_not_switch(self):
        (self.root/'params').write_text('UseKernelSuspendNotifiers: 0\n')
        self.assertNotEqual(self.run_helper('prepare').returncode, 0)
        self.assertFalse((self.root/'log').exists())
        self.assertFalse((self.root/'console').exists())

    def test_invalid_console_and_duplicate_prepare(self):
        (self.root/'vt').write_text('garbage\n')
        self.assertNotEqual(self.run_helper('prepare').returncode, 0)
        self.assertFalse((self.root/'console').exists())
        (self.root/'vt').write_text('1\n')
        self.assertEqual(self.run_helper('prepare').returncode, 0)
        self.assertNotEqual(self.run_helper('prepare').returncode, 0)
        self.assertEqual((self.root/'console').read_text(), '1\n')

    def test_failed_restore_retains_state(self):
        self.assertEqual(self.run_helper('prepare').returncode, 0)
        (self.root/'fail').touch()
        self.assertNotEqual(self.run_helper('restore').returncode, 0)
        self.assertEqual((self.root/'console').read_text(), '1\n')


if __name__ == '__main__':
    unittest.main()
