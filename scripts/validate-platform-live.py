#!/usr/bin/env python3
"""Capture P16 platform evidence, with optional temporary driver trials.

The default mode only reads status/SRAM/calibration metadata. Trials restore
the packaged SPI HID drivers and unload the trial Pluton module on exit.
No package, boot image, firmware or EFI variable is written by this script.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "build/live-validation.json"
CALIBRATION = "SCPCaliResult-da86db63-0b44-45a4-ad9a-254393010385"


def command(args, timeout=15):
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def check_target(dmi=Path("/sys/class/dmi/id"), *, architecture=None):
    """Scope board-specific trials; bound drivers validate resources and firmware ABIs."""
    if (architecture if architecture is not None else os.uname().machine) != "aarch64":
        raise RuntimeError("AArch64 required; no driver trial was started")
    for name, expected in (("sys_vendor", "ASUS"),
                           ("product_name", "ProArt P16 H7607BA")):
        if (dmi / name).read_text().strip() != expected:
            raise RuntimeError(f"Unsupported {name}; no driver trial was started")


def check_module(path):
    path = path.resolve(strict=True)
    if command(["modinfo", "-F", "vermagic", path]).split()[0] != os.uname().release:
        raise RuntimeError(f"Module kernel mismatch: {path}")
    return path


def check_sensor_bindings(driver=Path("/sys/bus/spi/drivers/spi_hid_acpi")):
    devices = [p for p in driver.iterdir() if p.is_symlink() and p.name != "module"]
    if len(devices) != 1 or devices[0].name != "spi-MSFW1111:00":
        raise RuntimeError("Expected exactly the P16 SPI sensor hub; refusing to unload shared transport")


def snapshot():
    result = {"kernel": os.uname().release, "dsp": {}}
    for device in ("NVDA8301:00", "NVDA8302:00", "NVDA8303:00"):
        path = Path("/sys/bus/platform/devices") / device
        item = {}
        for name in ("power/runtime_status", "power/control", "power/runtime_usage"):
            file = path / name
            item[name] = file.read_text().strip() if file.exists() else None
        item["driver"] = (path / "driver").resolve().name if (path / "driver").exists() else None
        result["dsp"][device] = item
    debug = Path("/sys/kernel/debug/n1x_scp")
    for name in ("status", "firmware_log"):
        if (debug / name).exists():
            result["scp_" + name] = (debug / name).read_text(errors="replace")
    if (debug / "sram_snapshot").exists():
        data = (debug / "sram_snapshot").read_bytes()
        if len(data) != 0x80000:
            raise RuntimeError("Unexpected SCP snapshot length")
        result["scp"] = {
            "code_crc32": hex(zlib.crc32(data[:0x13000])),
            "code_sha256": hashlib.sha256(data[:0x13000]).hexdigest(),
            "raw_sensor_words": list(struct.unpack_from("<5H", data, 0x569b0 + 0x40)),
            "calibration_enabled_raw": data[0x56668],
            "scale_coefficients_raw": [v if math.isfinite(v) else str(v)
                                       for v in struct.unpack_from("<26f", data, 0x569b0 + 0x68)],
        }
    variable = Path("/sys/firmware/efi/efivars") / CALIBRATION
    if variable.exists():
        data = variable.read_bytes()
        if len(data) < 4:
            raise RuntimeError("Truncated calibration EFI variable")
        result["calibration"] = {"variable": variable.name, "bytes": len(data) - 4,
                                 "attributes": hex(struct.unpack_from("<I", data)[0]),
                                 "data_sha256": hashlib.sha256(data[4:]).hexdigest()}
    return result


@contextmanager
def sensor_trial(core, acpi):
    # Validate everything before the first unload. Keep the keyboard/touchpad's
    # separate I2C transports and the SPI controller loaded throughout.
    check_sensor_bindings()
    core, acpi = check_module(core), check_module(acpi)
    for name in ("spi_hid", "spi_hid_acpi"):
        command(["modinfo", "-n", name])  # Packaged rollback module must exist.
    changed = new_core = new_acpi = False
    try:
        command(["rmmod", "spi_hid_acpi"])
        changed = True
        command(["rmmod", "spi_hid"])
        command(["insmod", core])
        new_core = True
        command(["insmod", acpi])
        new_acpi = True
        yield
    finally:
        if changed:
            # Restore the installed kernel's modules, including after a failed
            # insmod or sensor read. Do not claim restoration of a prior manual
            # development module which was never installed on disk.
            errors = []
            for inserted, name in ((new_acpi, "spi_hid_acpi"), (new_core, "spi_hid")):
                if inserted and (Path("/sys/module") / name).exists():
                    try:
                        command(["rmmod", name])
                    except Exception as error:
                        errors.append(str(error))
            # Still restore ACPI enumeration if an earlier unload failed.
            try:
                command(["modprobe", "spi_hid_acpi"])
            except Exception as error:
                errors.append(str(error))
            if errors:
                raise RuntimeError("SPI HID rollback needs attention: " + "; ".join(errors))


@contextmanager
def pluton_trial(module):
    module = check_module(module)
    device = Path("/sys/bus/platform/devices/NVDA8601:00")
    if (device / "driver").exists() or Path("/sys/module/n1x_pluton").exists():
        raise RuntimeError("ROT1 already has a driver; refusing to replace an existing instance")
    command(["insmod", module, "enable_transport=1"])
    try:
        yield
    finally:
        command(["rmmod", "n1x_pluton"])


def kernel_messages():
    return command(["dmesg", "--raw"]).splitlines()


def new_kernel_messages(before):
    old = set(before)
    return [line for line in kernel_messages() if line not in old]


def check_kernel_messages(lines):
    bad = [line for line in lines if
           re.search(r"BUG:|Oops:|Kernel panic|Call trace:", line) or
           (re.search(r"spi.?hid|n1x.?pluton|hid.sensor", line, re.I) and
            re.search(r"timed? ?out|timeout|failed|error|resetting", line, re.I))]
    if bad:
        raise RuntimeError("New kernel errors; trial stopped: " + "\n".join(bad))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--test-sensorhub", action="store_true")
    parser.add_argument("--test-pluton", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root; capture includes root-only SCP and EFI metadata")
    check_target()
    # Refuse to overwrite evidence from a prior experiment.
    if args.report.exists():
        parser.error("Report already exists; choose a new --report path")
    report = {"captured_at": datetime.now(timezone.utc).isoformat(), "before": snapshot(),
              "trials": {}, "functional_support_proven": False}
    failure = None
    try:
        if args.test_sensorhub:
            messages = kernel_messages()
            trial = report["trials"]["sensorhub"] = {}
            try:
                directory = ROOT / "platform/sensorhub"
                with sensor_trial(directory / "spi-hid.ko", directory / "spi-hid-acpi.ko"):
                    deadline = time.monotonic() + 3
                    while True:
                        devices = [p for p in Path("/sys/bus/iio/devices").glob("iio:device*")
                                   if (p / "name").read_text().strip() == "als" and "spi" in str(p.resolve())]
                        if len(devices) == 1:
                            break
                        if time.monotonic() >= deadline:
                            raise RuntimeError("Exactly one SPI ALS device did not enumerate")
                        time.sleep(0.1)
                    trial["iio_path"] = str(devices[0].resolve())
                    started = time.monotonic()
                    trial["first_raw_sample"] = command([
                        sys.executable, "-c", "import sys;from pathlib import Path;print(Path(sys.argv[1]).read_text().strip())",
                        devices[0] / "in_illuminance_raw"], timeout=8).strip()
                    trial["sample_seconds"] = time.monotonic() - started
                    trial["kernel_messages"] = new_kernel_messages(messages)
                    check_kernel_messages(trial["kernel_messages"])
                    trial["calibration_and_response_to_light"] = "not established by one raw sample"
            finally:
                trial["kernel_messages_including_rollback"] = new_kernel_messages(messages)
        if args.test_pluton:
            messages = kernel_messages()
            trial = report["trials"]["pluton"] = {}
            try:
                directory = ROOT / "platform/pluton"
                with pluton_trial(directory / "n1x_pluton.ko"):
                    cli = [sys.executable, directory / "pluton-info.py"]
                    trial["before_discovery"] = json.loads(command(cli))
                    trial["discovery"] = json.loads(command(cli + ["--discover"], timeout=13))
                    trial["after_discovery"] = json.loads(command(cli))
                    trial["kernel_messages"] = new_kernel_messages(messages)
                    check_kernel_messages(trial["kernel_messages"])
            finally:
                trial["kernel_messages_including_rollback"] = new_kernel_messages(messages)
    except Exception as error:
        report["error"] = str(error)
        failure = error
    finally:
        try:
            report["after"] = snapshot()
        except Exception as error:
            report["after_capture_error"] = str(error)
            if failure is None:
                failure = error
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(args.report)
    if failure:
        raise SystemExit(str(failure))


if __name__ == "__main__":
    main()
