#!/usr/bin/env python3
"""Bounded ALSA duplex qualification; optionally run device-only PM, never real sleep.

Creates private capture files and a JSON report. Does not alter mixer controls,
desktop services, power profiles, modules or boot files. A retained fault stops
the sequence. Device-only PM is a separate, explicit graphical polkit operation.
"""
import argparse
import errno
from datetime import datetime, timezone
from functools import cache
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import re

DEVICES = tuple(Path("/sys/bus/platform/devices") / f"NVDA830{i}:00" for i in (1, 2, 3))
FAULTS = ("error", "power_error", "ipc_error", "primary_error", "primary_task_error",
          "primary_pcm_error", "pcm_period_error")
VERSION = "0.1.25"
AFE_VERSION = "0.1.27"


def write_control(path, value):
    """One sysfs command, with no buffered close-time resubmission on error."""
    payload = value.encode('ascii')
    fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_TRUNC)
    try:
        if os.write(fd, payload) != len(payload):
            raise OSError(errno.EIO, 'Short sysfs control write')
    finally:
        os.close(fd)


def fields(text):
    return dict(item.split("=", 1) for item in text.split())


def snapshot():
    return {p.name: {name: (p / name).read_text().strip()
                     for name in ("status", "sleep_status", "asoc_ready")} for p in DEVICES}


def healthy(state, idle=True):
    for name, item in state.items():
        status, sleep = fields(item["status"]), fields(item["sleep_status"])
        if item["asoc_ready"] != "1" or status["ready"] != "1":
            raise RuntimeError(f"{name}: firmware/card not ready")
        if any(status[key] != "0" for key in FAULTS) or sleep["error"] != "0":
            raise RuntimeError(f"{name}: retained fault; no retry or reset")
        if sleep["suspended"] != "0" or sleep["irq_disabled"] != "0":
            raise RuntimeError(f"{name}: resume incomplete")
        if idle and status["primary_client"] != "0":
            raise RuntimeError(f"{name}: audio client active; leave it running and retry later")


@cache
def frontend_options():
    # Parameters are immutable during this validator; module maintenance is separate.
    paths = [Path("/sys/module/snd_soc_mt8901_afe/parameters", name)
             for name in ("dsp_playback", "dsp_capture")]
    try:
        return tuple(path.read_text().strip() for path in paths)
    except PermissionError:
        # A single read-only desktop authorization; PCM still runs as the user.
        values = subprocess.check_output(
            ["pkexec", "--disable-internal-agent", "/usr/bin/cat", *map(str, paths)],
            text=True, timeout=180).splitlines()
        if len(values) != len(paths):
            raise RuntimeError("Invalid AFE option readback")
        return tuple(values)


def preflight():
    if Path("/sys/module/n1x_adsp/version").read_text().strip() != VERSION:
        raise RuntimeError("Requires the matching DSP 0.1.25 / PCM ABI 3 candidate")
    afe_version = Path("/sys/module/snd_soc_mt8901_afe/version")
    if not afe_version.exists() or afe_version.read_text().strip() != AFE_VERSION:
        raise RuntimeError("Requires AFE 0.1.27 with capture IRQ ownership handoff")
    for name, value in zip(("dsp_playback", "dsp_capture"), frontend_options()):
        if value != "Y":
            raise RuntimeError(f"AFE {name} is not enabled on this boot")
    state = snapshot()
    healthy(state)
    return state


def sleep_unit(unit):
    result = subprocess.check_output(
        ['systemctl', 'show', unit, '--property=ActiveState', '--property=Job',
         '--property=Type', '--property=After'], text=True, timeout=10)
    return dict(line.split('=', 1) for line in result.splitlines() if '=' in line)


def sleep_service_finished():
    service, target = sleep_unit('systemd-suspend.service'), sleep_unit('suspend.target')
    return service.get('ActiveState') in ('inactive', 'failed') and \
        not service.get('Job') and not target.get('Job')


def device_pm():
    if os.geteuid() != 0:
        raise RuntimeError("Device PM requires the graphical pkexec operation")
    before = preflight()
    if "[s2idle]" not in Path("/sys/power/mem_sleep").read_text():
        raise RuntimeError("Only s2idle is admitted")
    control = Path("/sys/power/pm_test")
    if "[none]" not in control.read_text():
        raise RuntimeError("Another PM test is selected")
    for item in before.values():
        if fields(item["sleep_status"])["enabled"] != "1":
            raise RuntimeError("DSP system-sleep opt-in is disabled")
    service, target = sleep_unit('systemd-suspend.service'), sleep_unit('suspend.target')
    if service.get('Type') != 'oneshot' or \
            'systemd-suspend.service' not in target.get('After', '').split() or \
            target.get('ActiveState') != 'inactive' or not sleep_service_finished():
        raise RuntimeError('Requires an idle systemd suspend transaction with oneshot ordering')
    unresolved_request = False
    try:
        write_control(control, "devices\n")
        if '[devices]' not in control.read_text():
            raise RuntimeError('Device-only PM test was not selected; do not request sleep')
        # start waits for suspend.target's After=oneshot dependency to finish.
        # The asynchronous `systemctl suspend` verb cannot safely bracket
        # pm_test: clearing it after enqueueing could trigger real sleep later.
        unresolved_request = True
        try:
            subprocess.run(['systemctl', 'start', 'suspend.target'], check=True, timeout=180)
        except subprocess.CalledProcessError:
            unresolved_request = False
            raise
        else:
            unresolved_request = False
    finally:
        if unresolved_request or not sleep_service_finished():
            raise RuntimeError('Sleep transaction unresolved; pm_test remains devices for safety')
        write_control(control, "none\n")
    after = snapshot()
    healthy(after)
    for name, item in after.items():
        if int(fields(item["sleep_status"])["cycles"]) != int(fields(before[name]["sleep_status"])["cycles"]) + 1:
            raise RuntimeError(f"{name}: no completed fresh-ready resume cycle")
    return {"before": before, "after": after, "pm_test": control.read_text().strip(),
            "orchestration": "systemd suspend.target, synchronous oneshot dependency"}


def pcm_round(directory, phase, mode, fmt, seconds, playback, capture):
    before = preflight()
    ring = 8192 if fmt == "S16_LE" else 4096
    common = ["--file-type=raw", "--format=" + fmt, "--rate=48000", "--channels=2",
              "--period-size=1024", "--buffer-size=" + str(ring), "--duration=" + str(seconds)]
    recording = directory / f"{phase}-{mode}-{fmt}.raw"
    jobs = []
    try:
        for direction, device, program in (
                ("playback", playback, "aplay"), ("capture", capture, "arecord")):
            if mode != direction and mode != "duplex":
                continue
            command = [program, "--quiet", "--device=" + device, *common,
                       "/dev/zero" if direction == "playback" else str(recording)]
            log = directory / f"{phase}-{mode}-{fmt}-{direction}.log"
            with log.open("wb") as output:
                jobs.append(subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT))
        for job in jobs:
            if job.wait(timeout=seconds + 20):
                raise RuntimeError(f"{mode}/{fmt}: ALSA process failed; inspect its log")
    finally:
        for job in jobs:
            if job.poll() is None:
                job.terminate()
                try:
                    job.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    job.kill()
                    job.wait()
    after = snapshot()
    healthy(after)
    cores = ("NVDA8303:00",) if mode == "playback" else (
        ("NVDA8301:00",) if mode == "capture" else ("NVDA8301:00", "NVDA8303:00"))
    for core in cores:
        current = fields(after[core]["status"])
        if current["ipc_token"] == fields(before[core]["status"])["ipc_token"] or \
                int(current["pcm_notifications"]) < 2:
            raise RuntimeError(f"{core}: no sustained firmware PCM progress")
    result = {"phase": phase, "mode": mode, "format": fmt, "after": after}
    if mode != "playback":
        raw = recording.read_bytes()
        expected = seconds * 48000 * 2 * (2 if fmt == "S16_LE" else 4)
        if len(raw) != expected:
            raise RuntimeError(f"Capture length {len(raw)} != {expected}")
        result["capture"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                             "nonzero_bytes": sum(byte != 0 for byte in raw)}
        if not result["capture"]["nonzero_bytes"]:
            raise RuntimeError("Capture is all zero; verify routing and a known microphone stimulus")
    return result


def wait_for_soundwire(timeout=20):
    """SoundWire codec/card registration can finish after system PM returns."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        healthy(snapshot())
        ready = True
        for program in ('aplay', 'arecord'):
            result = subprocess.run([program, '-l'], capture_output=True, text=True, timeout=3)
            ready &= result.returncode == 0 and bool(re.search(
                r'^card [0-9]+: mt8901soundwire \[', result.stdout, re.M))
        if ready:
            return time.monotonic() - started
        time.sleep(0.1)
    raise RuntimeError('SoundWire playback/capture card did not reappear after resume')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seconds", type=int, default=3)
    parser.add_argument("--playback", default="hw:CARD=mt8901soundwire,DEV=0")
    parser.add_argument("--capture", default="hw:CARD=mt8901soundwire,DEV=8")
    parser.add_argument("--device-sleep", action="store_true",
                        help="after all idle PCM tests, request device-only PM through graphical pkexec, then repeat PCM tests")
    parser.add_argument("--device-pm", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.device_pm:
        print(json.dumps(device_pm()))
        return
    if not args.output or not 1 <= args.seconds <= 30:
        parser.error("Provide a new --output directory and --seconds between 1 and 30")
    before = preflight()
    directory = args.output.absolute()
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    # This process owns only its new output files. No global umask is restored in a parent.
    os.umask(0o077)
    report = {"created_at": datetime.now(timezone.utc).isoformat(),
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "kernel": os.uname().release, "before": before, "rounds": [], "completed": False}
    try:
        for phase in ("before", "after") if args.device_sleep else ("before",):
            if phase == "after":
                result = subprocess.check_output(
                    ["pkexec", "--disable-internal-agent", sys.executable, str(Path(__file__).resolve()), "--device-pm"],
                    text=True, timeout=180)
                report["device_pm"] = json.loads(result)
                report["alsa_resume_ready_seconds"] = wait_for_soundwire()
            for fmt in ("S16_LE", "S24_LE"):
                for mode in ("playback", "capture", "duplex"):
                    report["rounds"].append(pcm_round(directory, phase, mode, fmt, args.seconds,
                                                     args.playback, args.capture))
        report["completed"] = True
    except BaseException as error:
        report["error"] = str(error)
        raise
    finally:
        report["after"] = snapshot()
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(directory / "report.json", flush=True)


if __name__ == "__main__":
    main()
