#!/usr/bin/env python3
"""One-shot P16 DSP secure-boot trial; published DMA stays pinned until reboot.

Temporarily stages only pinned OEM firmware. Keeps native autoload disabled.
On a pre-publication failure, restores the stock driver and IOMMU modes.
After publication it never resets, retries, powers down or unloads the DSP.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT.parent / "n1x-lab"
SYS = Path("/sys/bus/platform/devices")
TARGETS = (("NVDA8301:00", "hifi5-0-mt8901-signed.bin", 0xc0304),
           ("NVDA8302:00", "hifi5-1-mt8901-signed.bin", 0xc0305),
           ("NVDA8303:00", "hifi1-0-mt8901-signed.bin", 0xc0303))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def run(args, timeout=30):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Command failed: " + " ".join(map(str, args)) + "\n" +
                           (result.stdout + result.stderr)[-10000:])
    return result.stdout


def fields(text):
    return dict(item.split("=", 1) for item in text.split() if "=" in item)


def publish_file(target, data):
    """Never overwrite a firmware file or follow a conflicting symlink."""
    if target.is_symlink() or (target.exists() and target.read_bytes() != data):
        raise RuntimeError("Preserving conflicting firmware: " + str(target))
    if target.exists():
        return False
    with tempfile.NamedTemporaryFile(prefix=".n1x-adsp-", dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.link(temporary, target)  # Atomic creation; EEXIST never overwrites.
        finally:
            temporary.unlink()
    return True


def state():
    result = {}
    for device, _, _ in TARGETS:
        path = SYS / device
        result[device] = {"driver": (path / "driver").resolve().name if (path / "driver").exists() else None,
                          "runtime": (path / "power/runtime_status").read_text().strip()}
        if (path / "status").exists():
            result[device]["status"] = fields((path / "status").read_text())
    return result


def any_published(snapshot):
    return any(item.get("status", {}).get("published") == "1" for item in snapshot.values())


def check_loader_api(symbols):
    if not re.search(r"^[0-9a-fA-F]+\s+[Tt]\s+n1x_sroot_client_ops_v4\s+"
                     r"\[n1x_npu_bootstrap\]$", symbols, re.M):
        raise RuntimeError("Loaded NPU module does not export the required loader ABI v4")


def check_boot_result(item, image_id):
    try:
        actual_image = int(item.get("image", "0"), 0)
    except ValueError as error:
        raise RuntimeError("Malformed DSP image ID; no retry") from error
    required = ("published", "loader_published", "loader_accepted",
                "loader_staging_released", "ready")
    if any(item.get(key) != "1" for key in required) or \
            item.get("error") != "0" or item.get("power_error") != "0" or actual_image != image_id:
        raise RuntimeError("DSP boot/ready and staging release not confirmed; no retry or reset")


def check_trial_manifest(manifest, release, boot_id, provider_version, dsp_version, afe_version):
    if manifest.get("kernel_release") != release:
        raise RuntimeError("Qualification manifest does not match the running kernel")
    source_boot = manifest.get("source_boot_id", "")
    if not isinstance(source_boot, str) or not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", source_boot) or source_boot == boot_id:
        raise RuntimeError("Qualification requires a fresh boot after preparing the bundle")
    for name, current in (("provider", provider_version), ("dsp", dsp_version), ("afe", afe_version)):
        expected = manifest.get("drivers", {}).get(name, {}).get("srcversion")
        if not expected or expected != current:
            raise RuntimeError("Qualification manifest source-version mismatch: " + name)
    if manifest.get("loader_abi") != 4:
        raise RuntimeError("Qualification manifest must require loader ABI v4")


def prepare_domains(modes):
    for device, _, _ in TARGETS:
        path = SYS / device
        if (path / "driver").exists():
            raise RuntimeError("DSP is still bound before IOMMU selection")
        group = (path / "iommu_group").resolve(strict=True)
        if {p.name for p in (group / "devices").iterdir()} != {device}:
            raise RuntimeError("Unexpected shared DSP IOMMU group")
        control = group / "type"
        modes[str(control)] = control.read_text().strip()
        if modes[str(control)] == "identity":
            control.write_text("DMA\n")
        if control.read_text().strip() not in ("DMA", "DMA-FQ"):
            raise RuntimeError("DSP isolated DMA domain not established")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--module", type=Path, help="explicit reviewed candidate; defaults to installed DKMS module")
    parser.add_argument("--installed", action="store_true", help="use only installed provider and firmware artifacts")
    parser.add_argument("--manifest", type=Path, help="pin the fresh kernel and DSP/provider/AFE source versions")
    args = parser.parse_args()
    if os.geteuid():
        parser.error("Run as root via sudo or pkexec")
    if args.report.exists():
        parser.error("Choose a new report path")
    live = module("platform_live", "validate-platform-live.py")
    probe = module("platform_probe", "validate-dsp-live.py")
    provider = module("platform_provider", "validate-sroot-provider.py")
    firmware = module("platform_firmware", "prepare-dsp-firmware.py")
    late = module("platform_late", "boot_audit.py")
    live.check_target()
    provider_module = "n1x_npu_bootstrap" if args.installed else LAB / "npu/driver/n1x_npu_bootstrap.ko"
    expected_provider = run(["modinfo", "-F", "srcversion", provider_module]).strip()
    npu = provider.snapshot()
    if npu.get("module_srcversion") != expected_provider or \
            npu.get("status", {}).get("task_verified") != "1" or \
            npu.get("status", {}).get("queue_poisoned") != "0":
        parser.error("The tested shared-loader provider is not healthy and loaded")
    check_loader_api(Path("/proc/kallsyms").read_text())
    candidate = live.check_module(args.module or Path(run(["modinfo", "-n", "n1x_adsp"]).strip()))
    manifest = None
    if args.manifest:
        manifest = json.loads(args.manifest.read_text())
        afe_version = Path("/sys/module/snd_soc_mt8901_afe/srcversion").read_text().strip()
        check_trial_manifest(manifest, os.uname().release,
                             Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                             expected_provider, run(["modinfo", "-F", "srcversion", candidate]).strip(),
                             afe_version)
        expected_dsp = manifest["drivers"]["dsp"].get("sha256")
        if expected_dsp != hashlib.sha256(candidate.read_bytes()).hexdigest():
            parser.error("DSP candidate bytes differ from the qualification manifest")
    if Path("/sys/module/n1x_adsp").exists():
        parser.error("Native DSP instance already exists; no replacement or retry")
    probe.wait_suspended(probe.ORIGINAL)
    if Path("/sys/module/snd_sof_mt8901/refcnt").read_text().strip() != "0":
        parser.error("Stock DSP module is busy")
    images = {}
    pins = {name: digest for name, digest in firmware.IMAGES.values()}
    for _, name, image_id in TARGETS:
        firmware_root = Path("/usr/lib/firmware/nvidia/n1x") if args.installed else LAB / "platform/firmware"
        data = (firmware_root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != pins[name]:
            parser.error("Unverified firmware: " + name)
        firmware.inspect_image(data, image_id)
        images[name] = data
    destination = Path("/usr/lib/firmware/nvidia/n1x")
    if destination.is_symlink():
        parser.error("Unexpected firmware-directory symlink")
    destination.mkdir(parents=True, exist_ok=True)
    hashes, messages = late.boot_hashes(), live.kernel_messages()
    report = {"provider_srcversion": expected_provider, "before": state(),
              "candidate": str(candidate), "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
              "automatic_boot_enabled": False, "boot_trials": {}, "firmware_sha256": pins,
              "loader_abi": 4, "qualification_manifest": manifest}
    created, modes = [], {}
    removed = inserted = published = False
    failure = None
    try:
        for name, data in images.items():
            target = destination / name
            if publish_file(target, data):
                created.append(target)
        run(["rmmod", "snd_sof_mt8901"])
        removed = True
        prepare_domains(modes)
        run(["insmod", candidate, "enable_boot=1"])
        inserted = True
        if Path("/sys/module/n1x_adsp/parameters/enable_boot").read_text().strip() != "Y":
            raise RuntimeError("Explicit boot parameter was not enabled")
        probe.wait_suspended("n1x-adsp")
        for device, _, image_id in TARGETS:
            print("Requesting one secure boot: " + device, flush=True)
            # A separate process bounds the userspace wait. A timeout is never
            # retried and does not imply the kernel transaction was cancelled.
            run(["/usr/bin/python", "-c",
                 "import os,sys;f=os.open(sys.argv[1],os.O_WRONLY);n=os.write(f,b'start\\n');os.close(f);assert n==6",
                 SYS / device / "boot"], timeout=70)
            snapshot = state()
            published = published or any_published(snapshot)
            item = snapshot[device]["status"]
            report["boot_trials"][device] = item
            check_boot_result(item, image_id)
            new_messages = live.new_kernel_messages(messages)
            live.check_kernel_messages(new_messages)
            if any(re.search(r"BUG:|Oops:|Kernel panic|Unhandled fault|translation fault", line, re.I) for line in new_messages):
                raise RuntimeError("New kernel fault; later DSP boots were not attempted")
        report["all_three_ready"] = True
    except Exception as error:
        report["error"] = str(error)
        failure = error
    finally:
        try:
            report["after_trials"] = state()
            published = published or any_published(report["after_trials"])
            report["needs_reboot_for_cleanup"] = published
            if not published:
                if inserted:
                    run(["rmmod", "n1x_adsp"])
                if removed:
                    for control, mode in modes.items():
                        if mode == "identity":
                            Path(control).write_text("identity\n")
                    run(["modprobe", "snd_sof_mt8901"])
                    report["restored"] = probe.wait_suspended(probe.ORIGINAL)
            for path in created:
                if not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == pins[path.name]:
                    path.unlink()
            report["after"] = state()
            report["kernel_messages"] = live.new_kernel_messages(messages)
            report["boot_artifacts_unchanged"] = hashes == late.boot_hashes()
            if not report["boot_artifacts_unchanged"]:
                raise RuntimeError("Unexpected boot-artifact change")
        except Exception as error:
            report["cleanup_error"] = str(error)
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
