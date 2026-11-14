import copy
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location(
    "audio_validation", Path(__file__).parents[1] / "scripts/validate-dsp-audio.py")
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


def state(cycles=0):
    status = dict.fromkeys(audio.FAULTS, "0")
    status.update(ready="1", primary_client="0", pcm_notifications="4", ipc_token="1")
    sleep = dict(enabled="1", error="0", suspended="0", irq_disabled="0", cycles=str(cycles))
    return {p.name: {"status": " ".join(f"{k}={v}" for k, v in status.items()),
                     "sleep_status": " ".join(f"{k}={v}" for k, v in sleep.items()),
                     "asoc_ready": "1"} for p in audio.DEVICES}


class AudioValidationTests(unittest.TestCase):
    def test_sysfs_write_error_is_never_replayed_on_close(self):
        import errno
        with patch.object(audio.os, "open", return_value=77), \
                patch.object(audio.os, "write", side_effect=OSError(errno.EBUSY, "busy")) as write, \
                patch.object(audio.os, "close") as close:
            with self.assertRaises(OSError):
                audio.write_control(Path("/sys/power/state"), "mem\n")
        write.assert_called_once_with(77, b"mem\n")
        close.assert_called_once_with(77)

    def test_resume_waits_for_both_playback_and_capture_card(self):
        card = "card 3: mt8901soundwire [mt8901-soundwire]"
        replies = [Mock(returncode=0, stdout=""), Mock(returncode=0, stdout=card),
                   Mock(returncode=0, stdout=card), Mock(returncode=0, stdout=card)]
        with patch.object(audio, "snapshot", return_value=state()), \
                patch.object(audio.subprocess, "run", side_effect=replies), \
                patch.object(audio.time, "sleep") as sleep:
            audio.wait_for_soundwire()
        sleep.assert_called_once()

    def test_all_retained_faults_and_clients_stop_the_sequence(self):
        baseline = state()
        audio.healthy(baseline)
        for device in baseline:
            for field in audio.FAULTS + ("ready", "primary_client"):
                changed = copy.deepcopy(baseline)
                fields = audio.fields(changed[device]["status"])
                fields[field] = "0" if field == "ready" else "1"
                changed[device]["status"] = " ".join(f"{k}={v}" for k, v in fields.items())
                with self.subTest(device=device, field=field), self.assertRaises(RuntimeError):
                    audio.healthy(changed)

    def pm_mocks(self, after=None):
        from contextlib import ExitStack
        stack = ExitStack()
        writes = []
        controls = {'/sys/power/pm_test': '[none] devices',
                    '/sys/power/mem_sleep': '[s2idle]'}
        class File:
            def __init__(self, name):
                self.name = str(name)
            def read_text(self):
                return controls[self.name]
        def write(path, value):
            writes.append((path.name, value))
            controls[path.name] = '[' + value.strip() + ']'
        def unit(name):
            return {'ActiveState': 'inactive', 'Job': '', 'Type': 'oneshot',
                    'After': 'systemd-suspend.service'}
        stack.enter_context(patch.object(audio.os, 'geteuid', return_value=0))
        stack.enter_context(patch.object(audio, 'preflight', return_value=state()))
        stack.enter_context(patch.object(audio, 'snapshot', return_value=after or state(1)))
        stack.enter_context(patch.object(audio, 'Path', side_effect=File))
        stack.enter_context(patch.object(audio, 'write_control', side_effect=write))
        stack.enter_context(patch.object(audio, 'sleep_unit', side_effect=unit))
        return stack, writes, controls

    def test_device_pm_waits_for_oneshot_target_before_clearing_test_mode(self):
        stack, writes, controls = self.pm_mocks()
        def start(command, **options):
            self.assertEqual(command, ['systemctl', 'start', 'suspend.target'])
            self.assertTrue(options['check'])
            self.assertEqual(controls['/sys/power/pm_test'], '[devices]')
        with stack, patch.object(audio.subprocess, 'run', side_effect=start) as run:
            audio.device_pm()
        run.assert_called_once()
        self.assertEqual(writes, [('/sys/power/pm_test', 'devices\n'),
                                  ('/sys/power/pm_test', 'none\n')])

    def test_completed_failed_sleep_restores_none_without_retry(self):
        stack, writes, _ = self.pm_mocks()
        with stack, patch.object(audio.subprocess, 'run', side_effect=
                                 subprocess.CalledProcessError(1, 'systemctl')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                audio.device_pm()
        run.assert_called_once()
        self.assertEqual([v for _,v in writes], ['devices\n', 'none\n'])

    def test_unresolved_sleep_keeps_device_test_selected_to_prevent_late_real_sleep(self):
        stack, writes, controls = self.pm_mocks()
        with stack, patch.object(audio, 'sleep_service_finished', side_effect=[True, False]), \
                patch.object(audio.subprocess, 'run', side_effect=subprocess.TimeoutExpired('systemctl', 180)):
            with self.assertRaisesRegex(RuntimeError, 'pm_test remains devices'):
                audio.device_pm()
        self.assertEqual([v for _,v in writes], ['devices\n'])
        self.assertEqual(controls['/sys/power/pm_test'], '[devices]')

    def test_timed_out_bus_request_retains_test_mode_even_if_units_look_idle(self):
        stack, writes, controls = self.pm_mocks()
        with stack, patch.object(audio.subprocess, 'run',
                                 side_effect=subprocess.TimeoutExpired('systemctl', 180)):
            with self.assertRaisesRegex(RuntimeError, 'pm_test remains devices'):
                audio.device_pm()
        self.assertEqual([v for _,v in writes], ['devices\n'])
        self.assertEqual(controls['/sys/power/pm_test'], '[devices]')

    def test_incomplete_resume_is_a_failure_after_pm_test_is_cleared(self):
        stack, writes, _ = self.pm_mocks(after=state())
        with stack, patch.object(audio.subprocess, 'run'):
            with self.assertRaisesRegex(RuntimeError, 'no completed'):
                audio.device_pm()
        self.assertEqual([v for _,v in writes], ['devices\n', 'none\n'])

    def test_old_driver_is_rejected_before_pcm_or_pm(self):
        with patch.object(audio, "Path") as path, patch.object(audio, "snapshot") as snapshot:
            path.return_value.read_text.return_value = "0.1.23"
            with self.assertRaisesRegex(RuntimeError, "matching DSP"):
                audio.preflight()
            snapshot.assert_not_called()

    def test_old_afe_is_rejected_before_authorization_or_pcm(self):
        with patch.object(audio, "Path") as path, \
                patch.object(audio, "frontend_options") as options:
            path.return_value.read_text.return_value = "0.1.25"
            path.return_value.exists.return_value = False
            with self.assertRaisesRegex(RuntimeError, "Requires AFE 0.1.27"):
                audio.preflight()
            options.assert_not_called()

    def test_pcm_timeout_terminates_only_the_own_test_process(self):
        from tempfile import TemporaryDirectory

        job = Mock()
        job.wait.side_effect = [subprocess.TimeoutExpired("aplay", 1), 0]
        job.poll.return_value = None
        with TemporaryDirectory() as directory, \
                patch.object(audio, "preflight", return_value=state()), \
                patch.object(audio.subprocess, "Popen", return_value=job):
            with self.assertRaises(subprocess.TimeoutExpired):
                audio.pcm_round(Path(directory), "before", "playback", "S16_LE", 1, "hw:0", "hw:8")
        job.terminate.assert_called_once_with()
        job.kill.assert_not_called()

    def test_private_options_use_one_read_only_authorization(self):
        audio.frontend_options.cache_clear()
        try:
            with patch.object(audio, "Path") as path, \
                    patch.object(audio.subprocess, "check_output", return_value="Y\nY\n") as command:
                path.return_value.read_text.side_effect = PermissionError("root-only option")
                self.assertEqual(audio.frontend_options(), ("Y", "Y"))
                self.assertEqual(audio.frontend_options(), ("Y", "Y"))
                command.assert_called_once()
                self.assertEqual(command.call_args.args[0][:3],
                                 ["pkexec", "--disable-internal-agent", "/usr/bin/cat"])
        finally:
            audio.frontend_options.cache_clear()

    def test_old_notifications_cannot_qualify_a_different_pcm(self):
        from tempfile import TemporaryDirectory

        job = Mock()
        job.wait.return_value = 0
        job.poll.return_value = 0
        with TemporaryDirectory() as directory, \
                patch.object(audio, "preflight", return_value=state()), \
                patch.object(audio, "snapshot", return_value=state()), \
                patch.object(audio.subprocess, "Popen", return_value=job):
            with self.assertRaisesRegex(RuntimeError, "no sustained"):
                audio.pcm_round(Path(directory), "before", "playback", "S16_LE", 1, "hw:0", "hw:8")


if __name__ == "__main__":
    unittest.main()
