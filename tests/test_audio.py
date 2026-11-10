"""Automatic audio startup validates all firmware identities before DMA changes."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('n1x_audio', str(ROOT/'platform/dsp/n1x-adsp-audio'))
spec = importlib.util.spec_from_loader(loader.name, loader)
audio = importlib.util.module_from_spec(spec)
loader.exec_module(audio)


class AudioStartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='n1x-audio-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.devices, self.controls = [], []
        for i, hid in enumerate(audio.HIDS):
            device = self.root/'bus/platform/devices'/(hid+':00')
            (device/'firmware_node').mkdir(parents=True)
            (device/'firmware_node/hid').write_text(hid+'\n')
            group = self.root/'kernel/iommu_groups'/str(i)
            (group/'devices').mkdir(parents=True)
            (group/'devices'/device.name).symlink_to(device)
            (group/'type').write_text('identity\n')
            (device/'iommu_group').symlink_to(group)
            self.devices.append(device)
            self.controls.append(group/'type')
        self.driver = self.root/'bus/platform/drivers/n1x-adsp'
        self.driver.mkdir(parents=True)

    def test_prepares_every_isolated_group_and_verifies_ready_components(self):
        audio.prepare(self.root)
        self.assertEqual([p.read_text() for p in self.controls], ['DMA\n']*3)
        for device in self.devices:
            (device/'driver').symlink_to(self.driver)
            (device/'asoc_ready').write_text('1\n')
        audio.prepare(self.root)  # Already prepared, bound providers are preserved.
        audio.verify(self.root)
        (self.devices[-1]/'asoc_ready').write_text('0\n')
        with self.assertRaisesRegex(RuntimeError, 'ASoC'):
            audio.verify(self.root)

    def test_shared_or_bound_last_group_does_not_change_earlier_domains(self):
        (self.controls[-1].parent/'devices/foreign').touch()
        with self.assertRaisesRegex(RuntimeError, 'Shared'):
            audio.prepare(self.root)
        self.assertEqual([p.read_text() for p in self.controls], ['identity\n']*3)
        (self.controls[-1].parent/'devices/foreign').unlink()
        (self.devices[-1]/'driver').symlink_to(self.driver)
        with self.assertRaisesRegex(RuntimeError, 'Bound'):
            audio.prepare(self.root)
        self.assertEqual([p.read_text() for p in self.controls], ['identity\n']*3)

    def test_missing_ambiguous_and_changed_firmware_identity_fail(self):
        (self.devices[-1]/'firmware_node/hid').write_text('NVDA9999\n')
        with self.assertRaisesRegex(RuntimeError, 'ACPI'):
            audio.prepare(self.root)
        (self.devices[-1]/'firmware_node/hid').write_text(audio.HIDS[-1]+'\n')
        other = self.devices[-1].with_name(audio.HIDS[-1]+':01')
        other.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'ACPI'):
            audio.prepare(self.root)
        other.rmdir()
        (self.devices[-1]/'firmware_node/hid').unlink()
        with self.assertRaises(OSError):
            audio.prepare(self.root)
        self.assertEqual([p.read_text() for p in self.controls], ['identity\n']*3)

    def test_unknown_domain_and_foreign_group_path_are_rejected(self):
        self.controls[-1].write_text('blocked\n')
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            audio.prepare(self.root)
        self.controls[-1].write_text('identity\n')
        (self.devices[-1]/'iommu_group').unlink()
        (self.devices[-1]/'iommu_group').symlink_to(self.root)
        with self.assertRaisesRegex(RuntimeError, 'group path'):
            audio.prepare(self.root)
        self.assertEqual([p.read_text() for p in self.controls], ['identity\n']*3)
