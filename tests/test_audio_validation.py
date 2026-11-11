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

    def test_device_pm_restores_none_even_if_suspend_write_fails(self):
        writes = []

        class File:
            def __init__(self, name):
                self.name = str(name)

            def read_text(self):
                return "[s2idle]" if self.name.endswith("mem_sleep") else "[none] devices"

            def write_text(self, value):
                writes.append((self.name, value))
                if self.name.endswith("/state"):
                    raise OSError("injected suspend failure")

        with patch.object(audio.os, "geteuid", return_value=0), \
                patch.object(audio, "preflight", return_value=state()), \
                patch.object(audio, "Path", side_effect=File):
            with self.assertRaises(OSError):
                audio.device_pm()
        self.assertEqual([value for _, value in writes], ["devices\n", "mem\n", "none\n"])

    def test_incomplete_resume_is_a_failure_after_pm_test_is_cleared(self):
        writes = []

        class File:
            def __init__(self, name):
                self.name = str(name)

            def read_text(self):
                return "[s2idle]" if self.name.endswith("mem_sleep") else "[none] devices"

            def write_text(self, value):
                writes.append(value)

        with patch.object(audio.os, "geteuid", return_value=0), \
                patch.object(audio, "preflight", return_value=state()), \
                patch.object(audio, "snapshot", return_value=state()), \
                patch.object(audio, "Path", side_effect=File):
            with self.assertRaisesRegex(RuntimeError, "no completed"):
                audio.device_pm()
        self.assertEqual(writes, ["devices\n", "mem\n", "none\n"])

    def test_old_driver_is_rejected_before_pcm_or_pm(self):
        with patch.object(audio, "Path") as path, patch.object(audio, "snapshot") as snapshot:
            path.return_value.read_text.return_value = "0.1.23"
            with self.assertRaisesRegex(RuntimeError, "matching DSP"):
                audio.preflight()
            snapshot.assert_not_called()

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
