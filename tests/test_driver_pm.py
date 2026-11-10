"""Run actual PM regressions and verify reproducible DKMS source packages."""
import hashlib
import re
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DriverPMTests(unittest.TestCase):
    def test_dsp_prepare_boot_and_inspection_serialization(self):
        subprocess.run(['python3', str(ROOT / 'platform/dsp/test_pm.py')],
                       check=True, timeout=40)

    def test_typed_pcm_card_and_pm_link_ownership(self):
        subprocess.run(['python3', str(ROOT / 'platform/dsp/test_card_client.py')],
                       check=True, timeout=40)

    def test_scp_reads_are_serialized_with_sleep(self):
        subprocess.run(['python3', str(ROOT / 'platform/scp/test_pm.py')],
                       check=True, timeout=40)

    def test_dkms_recipes_pin_the_current_source_bytes(self):
        for name in ('als', 'dsp', 'pluton', 'scp', 'sensorhub'):
            with self.subTest(driver=name):
                directory = ROOT / 'platform' / name
                records = subprocess.check_output(['bash', '-c',
                    'source PKGBUILD; '
                    '[[ ${#source[@]} == ${#sha256sums[@]} ]] || exit 1; '
                    'for ((i=0;i<${#source[@]};i++)); do '
                    'printf "%s\\t%s\\n" "${source[i]}" "${sha256sums[i]}"; done'],
                    cwd=directory, text=True)
                for record in records.splitlines():
                    filename, expected = record.split('\t')
                    self.assertEqual(hashlib.sha256((directory / filename).read_bytes()).hexdigest(),
                                     expected, f'{name}/{filename}')

    def test_dsp_module_dkms_and_package_versions_agree(self):
        directory = ROOT/'platform/dsp'
        package = re.search(r'^pkgver=(.+)$', (directory/'PKGBUILD').read_text(), re.M).group(1)
        module = re.search(r'MODULE_VERSION\("([^"\n]+)"\)',
                           (directory/'n1x_adsp.c').read_text()).group(1)
        dkms = re.search(r'^PACKAGE_VERSION="([^"\n]+)"$',
                         (directory/'dkms.conf').read_text(), re.M).group(1)
        self.assertEqual(module, package)
        self.assertEqual(dkms, package)
