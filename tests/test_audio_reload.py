"""Check maintenance ordering and service restoration without touching hardware."""
import errno
import importlib.machinery
import importlib.util
import json
import shutil
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
            if fault == 'future':
                (root / 'module/n1x_adsp/version').write_text('0.1.26')
                (root / 'module/snd_soc_mt8901_afe/version').write_text('0.1.28')
            if fault == 'old':
                (root / 'module/n1x_adsp/version').write_text('0.1.24')
            devices = []
            for hid in audio.HIDS:
                device = root / 'bus/platform/devices' / (hid + ':00')
                (device / 'firmware_node').mkdir(parents=True)
                (device / 'firmware_node/hid').write_text(hid)
                (device / 'shutdown').write_text('supported=1 attempted=0 power_off=0 released=0 error=0\n')
                (device / 'status').write_text('published=1 loader_published=1 loader_accepted=1 loader_staging_released=1')
                (device / 'asoc_ready').write_text('1')
                devices.append(device)
            if fault == 'unsupported':
                (devices[0] / 'shutdown').write_text('supported=0\n')
            state_path = root/'reload.json'
            module_files = {module: {str(p.relative_to(root/'module'/module)): p.read_text()
                                    for p in (root/'module'/module).rglob('*') if p.is_file()}
                            for module in ('n1x_adsp', 'snd_soc_mt8901_afe', 'mt8901_acp_sdw_legacy_mach')}
            if fault == 'unpublished':
                (devices[1]/'status').write_text('published=0 loader_published=0 loader_accepted=0 loader_staging_released=0')
            events = []
            original_write, original_stat = Path.write_text, Path.stat
            busy = False

            def write(path, value, *args, **kwargs):
                nonlocal busy
                if path.name != 'shutdown':
                    return original_write(path, value, *args, **kwargs)
                self.assertIn(value, ('stop\n', 'quiesce\n'))
                events.append((value.strip(), path.parent.name))
                if fault in ('timeout', 'timeout-resume'):
                    original_write(path, 'supported=1 attempted=1 power_off=0 released=0 error=-110\n')
                    raise OSError(errno.ETIMEDOUT, 'injected uncertain completion')
                if fault == 'busy-resume' or (fault == 'busy' and not busy):
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
                if arguments[:2] == ['/usr/bin/modprobe', '-r']:
                    if fault == 'unload-resume' and arguments[2] == 'n1x_adsp':
                        raise subprocess.CalledProcessError(1, arguments)
                    shutil.rmtree(root/'module'/arguments[2], ignore_errors=True)
                    if arguments[2] == 'n1x_adsp':
                        for device in devices:
                            (device/'shutdown').unlink(missing_ok=True)
                if fault == 'card-resume' and arguments[:2] == ['/usr/bin/modprobe', 'mt8901_acp_sdw_legacy_mach']:
                    raise subprocess.CalledProcessError(1, arguments)
                if arguments[0] == '/usr/bin/modprobe' and arguments[1] != '-r':
                    if fault in ('load', 'load-resume', 'stale-resume') and arguments[1] == 'n1x_adsp':
                        raise subprocess.CalledProcessError(1, arguments)
                    for name, value in module_files[arguments[1]].items():
                        path=root/'module'/arguments[1]/name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        original_write(path, value)
                if arguments[:2] == ['/usr/bin/modprobe', 'n1x_adsp']:
                    for device in devices:
                        original_write(device / 'shutdown', 'supported=1 attempted=0 power_off=0 released=0 error=0\n')
                        original_write(device/'asoc_ready', '0' if fault in ('firmware-resume','unknown-resume') else '1')
                        original_write(device/'status', 'published=1 loader_published=1 loader_accepted='+('0' if fault == 'unknown-resume' else '1')+' loader_staging_released=1')
                if fault == 'services-resume' and 'start' in arguments:
                    raise subprocess.CalledProcessError(1, arguments)
                return SimpleNamespace(returncode=0)

            real_save=audio.save_reload

            def save(path, state):
                if fault == 'journal-resume' and state['phase'] == 'loading':
                    raise OSError(errno.ENOSPC, 'injected stage-save failure')
                real_save(path, state)

            def ready(root):
                if (devices[0]/'asoc_ready').read_text() != '1':
                    raise RuntimeError('firmware not ready')

            with patch.object(audio.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='desktop')), \
                    patch.object(Path, 'stat', stat), patch.object(Path, 'write_text', write), \
                    patch.object(audio, 'replacement_modules', side_effect=RuntimeError('bad module file') if fault == 'preflight' else None), \
                    patch.object(audio, 'save_reload', side_effect=save), \
                    patch.object(audio, 'prepare'), patch.object(audio, 'verify',
                        side_effect=[RuntimeError('probe deferred'), None, None] if fault == 'deferred' else
                        ready), \
                    patch.object(audio, 'card_bound', return_value=True), patch.object(audio.time, 'sleep'):
                expected = {'preflight': RuntimeError, 'old': RuntimeError, 'unsupported': RuntimeError, 'timeout': OSError, 'load': subprocess.CalledProcessError}
                if fault and fault.endswith('-resume'):
                    first_error = (OSError if fault in ('busy-resume', 'timeout-resume','journal-resume') else RuntimeError
                                   if fault in ('firmware-resume','unknown-resume') else subprocess.CalledProcessError)
                    with self.assertRaises(first_error):
                        audio.reload_audio(1000, root, run, state_path=state_path)
                    state=json.loads(state_path.read_text())
                    expected_phase={'load-resume':'loading', 'firmware-resume':'loading', 'unknown-resume':'loading', 'stale-resume':'loading', 'card-resume':'loading',
                                    'unload-resume':'released','journal-resume':'released','busy-resume':'stopping',
                                    'timeout-resume':'stopping','services-resume':'restoring'}[fault]
                    self.assertEqual(state['phase'], expected_phase)
                    if fault == 'stale-resume':
                        state['boot_id']='another boot'
                        state_path.write_text(json.dumps(state))
                    before=len(events)
                    blocked=fault in ('timeout-resume','stale-resume','unknown-resume')
                    stopping=fault in ('busy-resume','firmware-resume')
                    restoring=fault == 'services-resume'
                    card_only=fault == 'card-resume'
                    fault=None
                    if blocked:
                        with self.assertRaises(RuntimeError):
                            audio.reload_audio(1000, root, run, resume=True, state_path=state_path)
                        self.assertEqual(len(events), before)
                        self.assertTrue(state_path.exists())
                    else:
                        audio.reload_audio(1000, root, run, resume=True, state_path=state_path)
                        self.assertFalse(state_path.exists())
                        if not stopping:
                            self.assertFalse(any(e[0] in ('quiesce','stop') for e in events[before:]))
                        if card_only:
                            self.assertFalse(any(e[:2] == ('/usr/bin/modprobe','n1x_adsp') for e in events[before:]))
                        if restoring:
                            self.assertFalse(any(e[0] == '/usr/bin/modprobe' for e in events[before:]))
                elif fault in expected:
                    with self.assertRaises(expected[fault]):
                        audio.reload_audio(1000, root, run, state_path=state_path)
                else:
                    audio.reload_audio(1000, root, run, state_path=state_path)
            return events

    def test_failed_stage_save_resumes_from_the_last_recorded_phase(self):
        self.exercise('journal-resume')

    def test_accepted_firmware_boot_can_recover_via_checked_native_shutdown(self):
        self.exercise('firmware-resume')

    def test_unknown_loader_result_is_never_replayed(self):
        self.exercise('unknown-resume')

    def test_never_published_core_needs_no_shutdown_transaction(self):
        events=self.exercise('unpublished')
        self.assertFalse(any(e[0] in ('quiesce','stop') and e[1] == 'NVDA8302:00' for e in events))

    def test_bad_replacement_is_rejected_before_audio_stops(self):
        self.assertEqual(self.exercise('preflight'), [])

    def test_load_failure_can_resume_without_repeating_power_shutdown(self):
        self.exercise('load-resume')

    def test_card_bind_retry_does_not_boot_the_ready_dsps_again(self):
        self.exercise('card-resume')

    def test_unload_failure_can_resume_from_released_stage(self):
        self.exercise('unload-resume')

    def test_busy_power_stage_can_continue_with_saved_machine_parameters(self):
        self.exercise('busy-resume')

    def test_resume_never_replays_an_uncertain_power_transaction(self):
        self.exercise('timeout-resume')

    def test_resume_rejects_a_journal_from_another_boot(self):
        self.exercise('stale-resume')

    def test_service_restoration_can_resume_without_touching_modules(self):
        self.exercise('services-resume')

    def test_old_running_driver_leaves_audio_untouched(self):
        self.assertEqual(self.exercise('old'), [])

    def test_later_driver_versions_with_same_shutdown_capability_can_reload(self):
        self.exercise('future')

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


class ReplacementPreflightTests(unittest.TestCase):
    def test_matching_modules_and_rejections_for_wrong_abi_old_driver_and_missing_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact=Path(directory)/'module.ko'
            artifact.write_bytes(b'test module metadata is mocked')
            for fault in (None, 'abi', 'old', 'missing'):
                calls=[]

                def capture(arguments, text, timeout):
                    self.assertTrue(text)
                    self.assertEqual(timeout, 15)
                    calls.append(arguments)
                    if arguments[0] == '/usr/bin/modprobe':
                        return 'insmod '+str(artifact if fault != 'missing' else artifact.with_name('absent.ko'))+'\n'
                    field, module=arguments[2:]
                    return {'vermagic': 'wrong release' if fault == 'abi' else audio.os.uname().release+' SMP',
                            'version': '0.1.24' if fault == 'old' else ('0.1.25' if module == 'n1x_adsp' else '0.1.27'),
                            'filename': str(artifact)}[field]

                if fault:
                    with self.assertRaises(RuntimeError):
                        audio.replacement_modules(capture)
                else:
                    audio.replacement_modules(capture)
                    self.assertEqual(sum(c[0] == '/usr/bin/modprobe' for c in calls),3)


if __name__ == '__main__':
    unittest.main()
