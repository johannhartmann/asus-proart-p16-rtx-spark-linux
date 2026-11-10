#!/usr/bin/env python3
"""Audit installed platform drivers using bounded firmware queries.

Writes only the requested report. Use --after-boot-id to require a new boot.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("n1x-scp-dkms", "n1x-pluton-dkms", "n1x-sensorhub-dkms", "n1x-adsp-dkms",
            "n1x-sroot-provider-dkms", "n1x-adsp-firmware-local", "n1x-sroot-firmware-local",
            "hid-sensor-als-dkms")


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def run(args, timeout=30):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Command failed: " + " ".join(map(str, args)) + "\n" +
                           (result.stdout + result.stderr)[-20000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--after-boot-id")
    args = parser.parse_args()
    if os.geteuid():
        parser.error("Run as root via sudo or pkexec")
    if args.report.exists():
        parser.error("Choose a new report path")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if args.after_boot_id == boot_id:
        parser.error("The requested reboot has not happened; no reboot verification claimed")
    live = load("audit_live", "validate-platform-live.py")
    provider = load("audit_provider", "validate-sroot-provider.py")
    late = load("audit_late", "boot_audit.py")
    verify = load("audit_boot", "verify-boot.py")
    firmware = load("audit_firmware", "prepare-dsp-firmware.py")
    live.check_target()
    report = {"captured_at": datetime.now(timezone.utc).isoformat(), "kernel": os.uname().release,
              "boot_id": boot_id, "reboot_verified": bool(args.after_boot_id),
              "dsp_service_integration": False, "pluton_pcbi_query_service_verified": False,
              "pluton_pcbi_control_service_integration": False,
              "sensor_calibration_accuracy": "unverified"}
    hashes, messages = late.boot_hashes(), live.kernel_messages()
    failure = None
    try:
        report["packages"] = run(["pacman", "-Q", *PACKAGES]).splitlines()
        report["dkms"] = run(["dkms", "status"], timeout=120)
        report["upower_critical_action"] = run([
            "busctl", "--system", "call", "org.freedesktop.UPower",
            "/org/freedesktop/UPower", "org.freedesktop.UPower", "GetCriticalAction"]).strip()
        if report["upower_critical_action"] != 's "PowerOff"':
            raise RuntimeError("Running UPower critical action is not PowerOff; restart upower")
        service = "n1x-platform-npu.service"
        report["npu_service_name"] = service
        report["npu_service"] = run(["systemctl", "show", service,
                                     "-p", "ActiveState", "-p", "Result", "-p", "ConditionResult"])
        if "ActiveState=active" not in report["npu_service"] or "Result=success" not in report["npu_service"]:
            raise RuntimeError("NPU boot service did not start successfully")
        report["npu"] = provider.snapshot()
        if report["npu"]["status"].get("task_verified") != "1" or \
                report["npu"]["status"].get("queue_poisoned") != "0":
            raise RuntimeError("NPU startup was not healthy")
        report["module_versions"] = {}
        for name in ("n1x_scp", "n1x_pluton", "spi_hid", "spi_hid_acpi", "n1x_npu_bootstrap", "hid_sensor_als"):
            path = Path("/sys/module") / name
            installed = run(["modinfo", "-n", name]).strip()
            built = run(["modinfo", "-F", "srcversion", name]).strip()
            loaded = (path / "srcversion").read_text().strip()
            if loaded != built:
                raise RuntimeError("Loaded/installed module differs: " + name)
            report["module_versions"][name] = {"path": installed, "srcversion": loaded}
        report["scp_version"] = Path("/sys/kernel/debug/n1x_scp/firmware_version").read_text().strip()
        report["pluton"] = json.loads(run(["n1x-pluton-info", "--discover", "--versions", "--services", "--device-info"],
                                           timeout=45))
        if 1 not in report['pluton'].get('pcbi_versions', []) or \
                {'id': 1, 'version': 1} not in report['pluton'].get('pcbi_services', []):
            raise RuntimeError('PCBI query service version 1 was not confirmed')
        report['pluton_pcbi_query_service_verified'] = True
        identity = report['pluton'].get('pcbi_device_info', {})
        if identity.get('platform_id') != 6 or not identity.get('packages'):
            raise RuntimeError('PCBI P16 firmware package metadata was not confirmed')
        report['pluton_pcbi_device_info_verified'] = True
        devices = [p for p in Path("/sys/bus/iio/devices").glob("iio:device*") if
                   (p / "name").read_text().strip() == "als" and "spi" in str(p.resolve())]
        if len(devices) != 1:
            raise RuntimeError("Exactly one SPI ALS device did not enumerate")
        sensor = devices[0]
        scale = float((sensor / "in_illuminance_scale").read_text().strip())
        report['als_channel_scales'] = {}
        for name, expected in (('in_illuminance_scale', 0.1), ('in_intensity_scale', 0.1),
                               ('in_colortemp_scale', 1.0), ('in_chromaticity_scale', 0.0001)):
            value = float((sensor / name).read_text().strip())
            report['als_channel_scales'][name] = value
            if value != expected:
                raise RuntimeError('ALS descriptor scale mismatch: ' + name)
        raw = []
        for _ in range(5):
            value = run(["/usr/bin/python", "-c",
                         "from pathlib import Path;import sys;print(Path(sys.argv[1]).read_text().strip())",
                         sensor / "in_illuminance_raw"], timeout=8).strip()
            raw.append(int(value))
        report["als"] = {"path": str(sensor.resolve()), "raw": raw, "scale": scale,
                          "lux": [value * scale for value in raw]}
        report["firmware"] = {}
        for name, expected in firmware.IMAGES.values():
            path = Path("/usr/lib/firmware/nvidia/n1x") / name
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError("Installed DSP firmware differs: " + name)
            report["firmware"][name] = actual
        report["dsp"] = {}
        for name in ("NVDA8301:00", "NVDA8302:00", "NVDA8303:00"):
            device = Path("/sys/bus/platform/devices") / name
            report["dsp"][name] = {"driver": (device / "driver").resolve().name,
                                   "runtime": (device / "power/runtime_status").read_text().strip()}
            if (device / "status").exists():
                report["dsp"][name]["status"] = (device / "status").read_text().strip()
        report["dsp_auto_boot_requested"] = "n1x_adsp.auto_boot=1" in Path("/proc/cmdline").read_text().split()
        if report["dsp_auto_boot_requested"]:
            report["dsp_audio_service"] = run([
                "systemctl", "show", "n1x-adsp-audio.service",
                "-p", "ActiveState", "-p", "Result", "-p", "ConditionResult"])
            if not all(value in report["dsp_audio_service"] for value in (
                    "ActiveState=active", "Result=success", "ConditionResult=yes")):
                raise RuntimeError("Automatic DSP audio service did not complete")
            # This helper only reads domains/readiness with --verify. Never
            # prepare, upload, reset or reload during an installation audit.
            run(["/usr/libexec/n1x-adsp-audio", "--verify"])
            for name, state in report["dsp"].items():
                device = Path("/sys/bus/platform/devices") / name
                state["asoc_ready"] = (device / "asoc_ready").read_text().strip()
                state["sleep_status"] = (device / "sleep_status").read_text().strip()
                if state["asoc_ready"] != "1":
                    raise RuntimeError("DSP ASoC component unavailable: " + name)
            for name in ("n1x_adsp", "snd_soc_mt8901_afe", "mt8901_acp_sdw_legacy_mach"):
                built = run(["modinfo", "-F", "srcversion", name]).strip()
                loaded = (Path("/sys/module") / name / "srcversion").read_text().strip()
                if loaded != built:
                    raise RuntimeError("Loaded/installed audio module differs: " + name)
                report["module_versions"][name] = {
                    "path": run(["modinfo", "-n", name]).strip(), "srcversion": loaded}
            report["dsp_service_integration"] = True
            # Firmware/ASoC readiness is distinct from physical audio tests.
            report["physical_audio_qualified"] = False
        report["default_entry"] = next(line for line in Path("/boot/limine.conf").read_text().splitlines()
                                        if line.startswith("default_entry:"))
        verify.verify_menu()
        report["limine_hashes_verified"] = True
    except Exception as error:
        report["error"] = str(error)
        failure = error
    finally:
        report["kernel_messages"] = live.new_kernel_messages(messages)
        report["boot_artifacts_unchanged"] = hashes == late.boot_hashes()
        try:
            live.check_kernel_messages(report["kernel_messages"])
            if not report["boot_artifacts_unchanged"]:
                raise RuntimeError("Unexpected boot-artifact change")
        except Exception as error:
            report["postflight_error"] = str(error)
            failure = failure or error
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(args.report, flush=True)
    if failure:
        raise SystemExit(str(failure))


if __name__ == "__main__":
    main()
