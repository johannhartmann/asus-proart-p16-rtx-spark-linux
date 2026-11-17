"""Exercise the installed Limine parser without changing host configuration."""
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = Path('/usr/lib/limine/limine-entry-tool')


class LimineCommandLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (CORE, Path('/etc/default/limine'),
                    Path('/etc/limine-entry-tool.conf'), Path('/etc/limine-entry-tool.d'))
        if not all(p.exists() for p in required) or not shutil.which('unshare'):
            raise unittest.SkipTest('Requires Limine and unprivileged Linux mount namespaces')
        result = subprocess.run(['unshare', '--user', '--map-root-user', '--mount',
                                 '--fork', '/usr/bin/true'], capture_output=True, timeout=10)
        if result.returncode:
            raise unittest.SkipTest('Unprivileged mount namespaces unavailable')

    def parse(self, policy):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'conf.d').mkdir()
            (root/'conf.d/zz-p16-keyboard.conf').write_text(policy)
            (root/'main.conf').write_text('ESP_PATH="/boot"\n')
            (root/'default.conf').write_text(
                'KERNEL_CMDLINE[default]+=root=/dev/test console=tty0 acpi=nospcr\n')
            script = '''set -eu
mount --make-rprivate /
mount --bind "$1/main.conf" /etc/limine-entry-tool.conf
mount --bind "$1/default.conf" /etc/default/limine
mount --bind "$1/conf.d" /etc/limine-entry-tool.d
exec /usr/lib/limine/limine-entry-tool --get-cmdline linux-p16-platform-36
'''
            result = subprocess.run(['unshare', '--user', '--map-root-user', '--mount',
                                     '--fork', 'bash', '-c', script, 'limine-regression',
                                     str(root)], text=True, capture_output=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Invalid arguments', result.stderr)
            self.assertFalse(result.stdout.startswith('Usage:'))
            return shlex.split(result.stdout.strip().splitlines()[-1])

    def test_packaged_osi_reaches_the_kernel_as_one_argument(self):
        before = Path('/etc/limine-entry-tool.d/zz-p16-keyboard.conf').read_bytes()
        original = self.parse('KERNEL_CMDLINE[default]+=\' acpi_osi="!Windows 2022"\'\n')
        fixed = self.parse((ROOT/'config/limine-p16-keyboard.conf').read_text())
        self.assertNotIn('acpi_osi=!Windows 2022', original)
        self.assertEqual(fixed.count('acpi_osi=!Windows 2022'), 1)
        for argument in ('root=/dev/test', 'console=tty0', 'acpi=nospcr'):
            self.assertIn(argument, fixed)
        self.assertEqual(Path('/etc/limine-entry-tool.d/zz-p16-keyboard.conf').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
