"""Peripheral installation checks with temporary roots and no live writes."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_installation as installation

REPO = installation.REPO
state = installation.state
peripherals = installation.module('peripherals', 'peripherals.py')


class PeripheralTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.staged = Path(self.temp.name) / 'staged'
        self.staged.mkdir()
        self.rows = []
        for name in peripherals.FIRMWARE_NAMES:
            data = name.encode()
            (self.staged / name).write_bytes(data)
            self.rows.append({'name': name, 'bytes': len(data),
                              'sha256': hashlib.sha256(data).hexdigest()})
        self.mock = patch.object(peripherals, 'manifest', return_value={'files': self.rows})
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_preserve_other_quirks_and_do_not_duplicate(self):
        original = '# owner settings\n[Other touchpad]\nMatchProduct=0x1234\n'
        updated = peripherals.touchpad_text(original)
        self.assertTrue(updated.startswith(original))
        self.assertEqual(peripherals.touchpad_text(updated), updated)

    def test_conflicting_policy_is_rejected(self):
        existing = (REPO / 'config/p16-touchpad.quirks').read_text().replace(
            'AttrPressureRange=none', 'AttrPressureRange=10:8')
        with self.assertRaisesRegex(ValueError, 'policy differs'):
            peripherals.touchpad_text(existing)

    def test_all_destinations_are_covered_by_backups(self):
        self.assertTrue(set(peripherals.PATHS).issubset(state.ADDED_CONFIG_PATHS))

    def test_later_conflicting_section_is_not_hidden_by_matching_section(self):
        existing = (REPO / 'config/p16-touchpad.quirks').read_text()
        conflict = existing.replace('[ASUS ProArt P16 Touchpad]', '[Competing P16 quirk]').replace(
            'AttrPalmPressureThreshold=0', 'AttrPalmPressureThreshold=100')
        with self.assertRaisesRegex(ValueError, 'policy differs'):
            peripherals.touchpad_text(existing + '\n' + conflict)

    def test_clean_install_then_no_op(self):
        changes = peripherals.plan(self.staged, self.root)
        self.assertEqual(set(changes), set(peripherals.PATHS))
        for name, content in changes.items():
            peripherals.atomic_write(self.root / name.lstrip('/'), content)
        self.assertEqual(peripherals.plan(self.staged, self.root), {})

    def test_corrupt_download_stops_before_any_live_write(self):
        (self.staged / peripherals.FIRMWARE_NAMES[-1]).write_bytes(b'wrong firmware')
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            peripherals.plan(self.staged, self.root)
        self.assertFalse(self.root.exists())

    def test_different_existing_firmware_is_not_replaced(self):
        target = self.root / peripherals.PATHS[-1].lstrip('/')
        target.parent.mkdir(parents=True)
        target.write_bytes(b'newer OEM firmware')
        with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
            peripherals.plan(self.staged, self.root)
        self.assertEqual(target.read_bytes(), b'newer OEM firmware')
        self.assertFalse((self.root / peripherals.QUIRKS.lstrip('/')).exists())

    def test_symlink_destination_is_rejected(self):
        target = self.root / peripherals.QUIRKS.lstrip('/')
        target.parent.mkdir(parents=True)
        target.symlink_to(self.staged / peripherals.FIRMWARE_NAMES[0])
        with self.assertRaisesRegex(ValueError, 'symlink'):
            peripherals.plan(self.staged, self.root)


class PeripheralRollbackTests(unittest.TestCase):
    def test_restore_preserves_original_quirks_and_removes_new_firmware(self):
        fixture = installation.BackupTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        quirks = fixture.root / peripherals.QUIRKS.lstrip('/')
        quirks.parent.mkdir(parents=True)
        original = b'# owner configuration\n[Other]\nMatchProduct=0x1234\n'
        quirks.write_bytes(original)
        (fixture.backup / 'state.json').unlink()
        state.begin(fixture.backup, fixture.packages, fixture.root)
        quirks.write_text(peripherals.touchpad_text(original.decode()))
        for name in peripherals.PATHS[1:]:
            target = fixture.root / name.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'new firmware')
        state.restore(fixture.backup, fixture.root, status='failed')
        self.assertEqual(quirks.read_bytes(), original)
        for name in peripherals.PATHS[1:]:
            self.assertFalse((fixture.root / name.lstrip('/')).exists())
