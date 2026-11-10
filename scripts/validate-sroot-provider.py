#!/usr/bin/env python3
"""Trial the shared SROOT provider through checked NPU stop/reload and inference.

No package/boot artifact is changed. A failed stop or uncertain startup is
terminal: retain the loaded instance for inspection, never force removal.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NPU = ROOT.parent / "n1x-lab/npu"
ENDPOINT = Path("/sys/bus/platform/devices/NVDA200A:00")
MODULE = Path("/sys/module/n1x_npu_bootstrap")
DEBUG = Path("/sys/kernel/debug/n1x-npu-bootstrap")


def run(args, timeout=60):
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Command failed: " + " ".join(map(str, args)) + "\n" +
                           (result.stdout + result.stderr)[-20000:])
    return result.stdout


def fields(text):
    return dict(item.split("=", 1) for item in text.split() if "=" in item)


def status(name):
    for directory in (DEBUG, ENDPOINT):
        file = directory / name
        if file.exists():
            return fields(file.read_text())
    raise RuntimeError("Missing NPU status interface: " + name)


def info():
    with open("/dev/accel/accel0", "rb", buffering=0) as device:
        buffer = bytearray(48)
        fcntl.ioctl(device, 0x80306440, buffer, True)
    return dict(zip(("abi_version", "capabilities", "max_image_bytes", "max_addresses",
                     "retained_bytes", "retain_limit", "retained_jobs", "max_jobs", "reserved"),
                    struct.unpack("<4I2Q2IQ", buffer)))


def snapshot():
    result = {}
    if MODULE.exists():
        result["module_srcversion"] = (MODULE / "srcversion").read_text().strip()
        result["module_refcnt"] = (MODULE / "refcnt").read_text().strip()
        for name in ("status", "hfrp_status", "shutdown_status"):
            result[name] = status(name)
    if Path("/dev/accel/accel0").exists():
        result["info"] = info()
    return result


def trigger_stop():
    with (ENDPOINT / "shutdown").open("wb", buffering=0) as control:
        if control.write(b"stop\n") != 5:
            raise RuntimeError("Short stop request; no retry permitted")


def checked_stop_and_unload(report):
    before = report["before"] = snapshot()
    state, hfrp, device = before["status"], before["hfrp_status"], before["info"]
    if device["abi_version"] != 2 or not device["capabilities"] & 8:
        raise RuntimeError("Loaded driver does not advertise the checked-stop ABI")
    if device["retained_jobs"] or device["retained_bytes"] or before["module_refcnt"] != "0":
        raise RuntimeError("NPU clients or retained jobs exist; no stop attempted")
    if any(state.get(key) != "1" for key in
           ("dla_bound", "sroot_bound", "idle_observed", "ping_verified", "region5_registered",
            "config_valid", "config_apply_accepted", "lpwr_accepted", "task_verified")) or \
            state.get("queue_poisoned") != "0" or state.get("error") != "0" or \
            hfrp.get("error") != "0" or hfrp.get("power_accepted") != "1":
        raise RuntimeError("NPU startup/queue is not healthy; no stop attempted")
    if before["shutdown_status"].get("attempted") != "0":
        raise RuntimeError("A stop was already attempted; no automatic retry")
    trigger_stop()
    report["after_stop"] = snapshot()
    shutdown = report["after_stop"]["shutdown_status"]
    if any(shutdown.get(key) != value for key, value in
           {"error": "0", "hardware_off": "1", "released": "1",
            "hfrp_held": "0", "upload_held": "0"}.items()):
        raise RuntimeError("Checked stop was not confirmed; module remains loaded")
    if report["after_stop"]["module_refcnt"] != "0" or \
            report["after_stop"]["info"]["retained_bytes"] or \
            report["after_stop"]["info"]["retained_jobs"]:
        raise RuntimeError("NPU has outstanding references after stop; no unload attempted")
    run(["rmmod", "n1x_npu_bootstrap"])
    if MODULE.exists() or (ENDPOINT / "driver").exists() or Path("/dev/accel/accel0").exists():
        raise RuntimeError("NPU removal incomplete; no reload attempted")
    report["old_module_unloaded"] = True


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_dma():
    for name in ("NVDA200A:00", "NVDA8600:00"):
        device = ENDPOINT.parent / name
        if (device / "driver").exists():
            raise RuntimeError("Endpoint is still bound before candidate load")
        group = (device / "iommu_group").resolve(strict=True)
        if {path.name for path in (group / "devices").iterdir()} != {name}:
            raise RuntimeError("Shared IOMMU group; candidate load was not attempted")
        mode = group / "type"
        current = mode.read_text().strip()
        if current == "identity":
            mode.write_text("DMA\n")
            current = mode.read_text().strip()
        if current not in ("DMA", "DMA-FQ"):
            raise RuntimeError("No isolated DMA domain; candidate load was not attempted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=NPU / "driver/n1x_npu_bootstrap.ko")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid():
        parser.error("Run as root via sudo or pkexec")
    if args.report.exists() or args.report.with_suffix("").exists():
        parser.error("Choose a new report path")
    live = load_script("platform_live", "validate-platform-live.py")
    late = load_script("platform_late", "boot_audit.py")
    live.check_target()
    candidate = live.check_module(args.candidate)
    source_version = run(["modinfo", "-F", "srcversion", candidate]).strip()
    if source_version != run(["modinfo", "-F", "srcversion", NPU / "driver/n1x_npu_bootstrap.ko"]).strip():
        parser.error("Candidate differs from the reviewed build used by numerical qualification")
    if not re.search(r"\bT n1x_sroot_client_ops_v4$", run(["nm", "-g", candidate]), re.M):
        parser.error("Candidate lacks the device-bound SROOT provider ABI v4")
    report = {"candidate": str(candidate), "candidate_srcversion": source_version,
              "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
              "old_module_unloaded": False, "new_module_loaded": False,
              "dsp_firmware_started": False, "packages_installed": False}
    hashes, messages = late.boot_hashes(), live.kernel_messages()
    directory = args.report.with_suffix("")
    directory.mkdir(parents=True)
    owner = int(os.environ["PKEXEC_UID"]) if "PKEXEC_UID" in os.environ else None
    if owner is not None:
        os.chown(directory, owner, -1)
    failure = None
    try:
        checked_stop_and_unload(report)
        prepare_dma()
        run(["insmod", candidate])
        report["new_module_loaded"] = True
        report["after_load"] = snapshot()
        if report["after_load"]["module_srcversion"] != source_version or \
                report["after_load"]["status"].get("task_verified") != "1" or \
                report["after_load"]["status"].get("queue_poisoned") != "0":
            raise RuntimeError("Candidate startup was not confirmed; no retry or unload")
        for label, options in (("numerical", []), ("reuse", ["--reuse"])):
            command = [NPU / "venv/bin/python", NPU / "scripts/qualify_cudla.py",
                       "--output-dir", directory / label] + options
            print("Running NPU " + label + " qualification", flush=True)
            report[label] = run(command, timeout=120)[-20000:]
        report["numerical_inference_verified"] = True
    except Exception as error:
        report["error"] = str(error)
        failure = error
    finally:
        try:
            report["after"] = snapshot()
            report["kernel_messages"] = live.new_kernel_messages(messages)
            report["boot_artifacts_unchanged"] = hashes == late.boot_hashes()
            if not report["boot_artifacts_unchanged"]:
                raise RuntimeError("Unexpected boot-artifact change")
            live.check_kernel_messages(report["kernel_messages"])
            if any(re.search(r"automatic startup failed|BUG:|Oops:|Kernel panic|Unhandled fault|translation fault", line, re.I)
                   for line in report["kernel_messages"]):
                raise RuntimeError("New kernel fault/startup failure; inspect retained state")
        except Exception as error:
            report["postflight_error"] = str(error)
            failure = failure or error
        with args.report.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(args.report, flush=True)
    if failure:
        raise SystemExit(str(failure))


if __name__ == "__main__":
    main()
