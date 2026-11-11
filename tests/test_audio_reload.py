"""Check maintenance ordering and service restoration without touching hardware."""
import errno
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('audio_reload', str(ROOT / 'platform/dsp/n1x-adsp-audio'))
spec = importlib.util.spec_from_loader(loader.name, loader)
audio = importlib.util.module_from_spec(spec)
loader.exec_module(audio)


class AudioReloadTests(unittest.TestCase):
    def exercise(self, fault=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for module, version, params in (
                    ('n1x_adsp', '0.1.25', ('enable_boot', 'auto_boot', 'enable_retention_sleep')),
                    ('snd_soc_mt8901_afe', '0.1.27', ('dsp_playback', 'dsp_capture')),
                    ('mt8901_acp_sdw_legacy_mach', None, ('dsp_playback',))):
                base = root / 'module' / module
                (base / 'parameters').mkdir(parents=True)
                if version:
                    (base / 'version').write_text(version)
                for name in params:
                    (base / 'parameters' / name).write_text('Y\n')
            devices = []
            for hid in audio.HIDS:
                device = root / 'bus/platform/devices' / (hid + ':00')
                (device / 'firmware_node').mkdir(parents=True)
                (device / 'firmware_node/hid').write_text(hid)
                (device / 'shutdown').write_text('supported=1 attempted=0 power_off=0 released=0 error=0\n')
                devices.append(device)
            if fault == 'unsupported':
                (devices[0] / 'shutdown').write_text('supported=0\n')
            events = []
            original_write, original_stat = Path.write_text, Path.stat
            busy = False

            def write(path, value, *args, **kwargs):
                nonlocal busy
                if path.name != 'shutdown':
                    return original_write(path, value, *args, **kwargs)
                self.assertIn(value, ('stop\n', 'quiesce\n'))
                events.append((value.strip(), path.parent.name))
                if fault == 'timeout':
                    original_write(path, 'supported=1 attempted=1 power_off=0 released=0 error=-110\n')
                    raise OSError(errno.ETIMEDOUT, 'injected uncertain completion')
                if fault == 'busy' and not busy:
                    busy = True
                    original_write(path, 'supported=1 attempted=1 power_off=0 released=0 error=-16\n')
                    raise OSError(errno.EBUSY, 'not submitted')
                return original_write(path, 'supported=1 attempted=1 power_off=1 released=' + ('1' if value == 'stop\n' else '0') + ' error=0\n')

            def stat(path, *args, **kwargs):
                if str(path) == '/run/user/1000':
                    return SimpleNamespace(st_uid=1000)
                return original_stat(path, *args, **kwargs)

            def run(arguments, check, timeout):
                self.assertEqual(timeout, 180)
                events.append(tuple(arguments))
                if 'is-active' in arguments:
                    return SimpleNamespace(returncode=0 if arguments[-1] == 'pipewire.socket' else 3)
                if arguments[:3] == ['/usr/bin/modprobe', '-r', 'n1x_adsp']:
                    for device in devices:
                        (device / 'shutdown').unlink()
                if arguments[:2] == ['/usr/bin/modprobe', 'n1x_adsp']:
                    if fault == 'load':
                        raise subprocess.CalledProcessError(1, arguments)
                    for device in devices:
                        original_write(device / 'shutdown', 'supported=1 attempted=0 power_off=0 released=0 error=0\n')
                return SimpleNamespace(returncode=0)

            with patch.object(audio.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='desktop')), \
                    patch.object(Path, 'stat', stat), patch.object(Path, 'write_text', write), \
                    patch.object(audio, 'prepare'), patch.object(audio, 'verify',
                        side_effect=[RuntimeError('probe deferred'), None] if fault == 'deferred' else None), \
                    patch.object(audio, 'card_bound', return_value=True), patch.object(audio.time, 'sleep'):
                expected = {'unsupported': RuntimeError, 'timeout': OSError, 'load': subprocess.CalledProcessError}
                if fault in expected:
                    with self.assertRaises(expected[fault]):
                        audio.reload_audio(1000, root, run)
                else:
                    audio.reload_audio(1000, root, run)
            return events

    def test_unsupported_kernel_leaves_audio_and_modules_untouched(self):
        self.assertEqual(self.exercise('unsupported'), [])

    def test_success_stops_secondary_first_and_preserves_module_options(self):
        events = self.exercise()
        self.assertEqual([event[1] for event in events if event[0] == 'stop'],
                         ['NVDA8302:00', 'NVDA8301:00', 'NVDA8303:00'])
        self.assertIn(('/usr/bin/modprobe', 'snd_soc_mt8901_afe', 'dsp_playback=1', 'dsp_capture=1'), events)
        self.assertTrue(any(event[-2:] == ('start', 'pipewire.socket') for event in events))

    def test_unknown_completion_is_not_retried_or_unloaded(self):
        events = self.exercise('timeout')
        self.assertEqual(sum(event[0] in ('stop', 'quiesce') for event in events), 1)
        self.assertNotIn(('/usr/bin/modprobe', '-r', 'n1x_adsp'), events)
        self.assertTrue(any(event[-2:] == ('start', 'pipewire.socket') for event in events))

    def test_deferred_probe_gets_time_to_publish_asoc_components(self):
        events = self.exercise('deferred')
        self.assertTrue(any(event[:2] == ('/usr/bin/modprobe', 'mt8901_acp_sdw_legacy_mach') for event in events))

    def test_unsubmitted_stage_can_retry(self):
        events = self.exercise('busy')
        self.assertEqual(sum(event[0] in ('stop', 'quiesce') for event in events), 7)

    def test_load_failure_restores_services_even_with_missing_dsp_attributes(self):
        events = self.exercise('load')
        self.assertTrue(any(event[-2:] == ('start', 'pipewire.socket') for event in events))


if __name__ == '__main__':
    unittest.main()
