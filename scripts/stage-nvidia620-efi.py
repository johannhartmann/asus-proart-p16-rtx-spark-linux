#!/usr/bin/env python3
"""Publish a verified 620 UKI under a distinct EFI name and create-only entry.

This is a preboot stage. It never sets BootNext, changes Limine's menu, or
reboots. efibootmgr -C creates a UEFI entry without adding it to BootOrder.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import importlib.util


HERE = Path(__file__).resolve().parent
DEST = Path("/boot/EFI/Linux/p16_nvidia620_kernel38.efi")
LABEL = "P16 Kernel38 NVIDIA 620 Candidate"
LOADER = r"\EFI\Linux\p16_nvidia620_kernel38.efi"


def sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UKI = sibling("p16_nvidia620_uki_stage", "stage-nvidia620-uki.py")
SNAPSHOT = UKI.SNAPSHOT


def run(command, *, timeout=60):
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}: "
                           + result.stderr[-1200:] + result.stdout[-500:])
    return result.stdout


def entry_ids(output):
    return set(re.findall(r"^Boot([0-9A-Fa-f]{4})\*?\s", output, re.MULTILINE))


def disk_partition():
    partition = Path(run(["/usr/bin/findmnt", "-n", "-o", "SOURCE", "/boot"]).strip())
    if not partition.is_block_device():
        raise RuntimeError("/boot is not on a block device")
    columns = run(["/usr/bin/lsblk", "-n", "-o", "PKNAME,PARTN",
                   str(partition)]).strip().split()
    if len(columns) != 2 or not columns[1].isdigit():
        raise RuntimeError("could not derive the EFI disk and partition")
    disk = Path("/dev") / columns[0]
    if not disk.is_block_device():
        raise RuntimeError("EFI parent disk is not a block device")
    return disk, columns[1]


def verify_candidate_userspace(root):
    # The signed 620 archive passed pacman -Qkk while missing a transitive
    # ARM64 dependency. Load and relocate the libraries with the candidate's
    # own loader. Do not pass the live 615 GPU through to that process.
    if (root / "dev/nvidiactl").exists() or (root / "dev/dri").exists():
        raise RuntimeError("candidate userspace validation requires an isolated /dev")
    probe = """
import ctypes
import json
import os
from pathlib import Path

libraries = {
    "libEGL_nvidia.so.0": "__egl_Main",
    "libnvidia-eglcore.so.620.70.06": None,
    "libGLX_nvidia.so.0": "__glx_Main",
    "libnvidia-egl-gbm.so.1": "loadEGLExternalPlatform",
    "/usr/lib/gbm/nvidia-drm_gbm.so": "gbmint_get_backend",
    "libcuda.so.1": "cuInit",
    "libnvidia-ml.so.1": "nvmlInit_v2",
    "libnvidia-encode.so.1": "NvEncodeAPICreateInstance",
    "libnvcuvid.so.1": "cuvidCreateDecoder",
}
for library, symbol in libraries.items():
    handle = ctypes.CDLL(library, mode=os.RTLD_NOW | os.RTLD_LOCAL)
    if symbol:
        getattr(handle, symbol)
for path, key, expected in (
    ("/usr/share/glvnd/egl_vendor.d/10_nvidia.json", "ICD", "libEGL_nvidia.so.0"),
    ("/usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json", "ICD", "libnvidia-egl-gbm.so.1"),
    ("/usr/share/vulkan/icd.d/nvidia_icd.json", "ICD", "libGLX_nvidia.so.0"),
):
    if json.loads(Path(path).read_text())[key]["library_path"] != expected:
        raise ValueError(f"Unexpected NVIDIA loader manifest: {path}")
"""
    run(["/usr/bin/chroot", str(root), "/usr/bin/env", "-i",
         "/usr/bin/python3", "-I", "-S", "-B", "-c", probe])


def verify_candidate_root(state, manifest, image):
    listing = run(["/usr/bin/btrfs", "subvolume", "list", "/"])
    matches = re.findall(r"^ID (\d+)\s+.*\bpath @nvidia620$", listing, re.MULTILINE)
    if matches != [str(manifest["candidate_id"])]:
        raise RuntimeError("@nvidia620 is missing or differs from the verified UKI root")
    work = Path(tempfile.mkdtemp(prefix="p16-nvidia620-efi-check-", dir="/run"))
    root = work / "candidate"
    root.mkdir(mode=0o700)
    mounted = False
    try:
        run(["/usr/bin/mount", "-t", "btrfs", "-o", "ro,subvol=@nvidia620",
             state["mount"]["device"], str(root)])
        mounted = True
        if SNAPSHOT.snapshot_id(root) != manifest["candidate_id"]:
            raise RuntimeError("mounted candidate has a different subvolume ID")
        UKI.candidate_versions(root)
        verify_candidate_userspace(root)
        module_dir = root / "usr/lib/modules" / UKI.RELEASE
        for name, record in manifest["checks"]["embedded_nvidia"].items():
            found = list(module_dir.rglob(name + ".ko*"))
            if len(found) != 1 or UKI.digest(found[0]) != record["installed_sha256"]:
                raise RuntimeError("candidate NVIDIA module changed after UKI build: " + name)
        kernel = (module_dir / "vmlinuz").read_bytes()
        if UKI.BOOT.sections(image)[".linux"][:len(kernel)] != kernel:
            raise RuntimeError("candidate kernel changed after UKI build")
    finally:
        if mounted:
            # Never remove a directory beneath a failed private unmount.
            run(["/usr/bin/umount", str(root)])
        root.rmdir()
        work.rmdir()


def validate_stage(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    image = directory / "kernel38-nvidia620.efi"
    if manifest.get("pass") is not True or manifest.get("candidate_subvolume") != "@nvidia620" or \
            manifest.get("boot_files_written") is not False or \
            manifest.get("hardware_qualified") is not False:
        raise RuntimeError("UKI stage receipt is not a passing preboot build")
    expected = manifest.get("checks", {}).get("image_sha256")
    if not isinstance(expected, str) or len(expected) != 64 or UKI.digest(image) != expected:
        raise RuntimeError("staged UKI hash differs from its receipt")
    sections = UKI.BOOT.sections(image)
    release = sections[".uname"].rstrip(b"\0\n").decode()
    cmdline = sections[".cmdline"].rstrip(b"\0\n").decode()
    profile = UKI.PREPARE.DSP.check_cmdline(cmdline, release, UKI.RELEASE,
                                             "@nvidia620", str(image))
    if not profile["pass"]:
        raise RuntimeError("staged UKI release/audio/root profile failed")
    return manifest, image, profile


def restore_boot_order(before):
    current = SNAPSHOT.boot_state()
    if current["BootOrder"] != before["BootOrder"]:
        order = before["BootOrder"].split(":", 1)[1].strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{4}(?:,[0-9A-Fa-f]{4})*", order):
            raise RuntimeError("cannot safely restore the original BootOrder")
        run(["/usr/bin/efibootmgr", "-o", order])
    if SNAPSHOT.boot_state()["BootOrder"] != before["BootOrder"]:
        raise RuntimeError("BootOrder did not return to its original value")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uki-stage-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="new JSON receipt outside EFI")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run through graphical Polkit as root")
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(Path("/boot")) or \
            output.is_relative_to(Path("/efi")) or output.is_relative_to(Path("/run")):
        parser.error("choose a new durable receipt outside EFI and /run")
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_tmp = output.parent / (output.name + ".staging-" + str(os.getpid()))
    if receipt_tmp.exists():
        parser.error("temporary receipt path already exists")
    stage, image, profile = validate_stage(args.uki_stage_dir.resolve(strict=True))
    state = SNAPSHOT.plan()
    if not state["ready_to_stage"] or state["boot"]["BootNext"] is not None:
        raise RuntimeError("live package/boot preflight is not ready")
    if state["packages"] != stage["live_packages_after"] or \
            state["boot"] != stage["boot_after"] or \
            SNAPSHOT.boot_hashes() != stage["efi_sha256_after"]:
        raise RuntimeError("rollback state differs from the UKI build receipt")
    verify_candidate_root(state, stage, image)
    if DEST.exists() or (DEST.parent / (DEST.name + ".staging-" + str(os.getpid()))).exists():
        raise RuntimeError("candidate EFI path already exists")
    if image.stat().st_size + 16 * 1024 * 1024 > shutil.disk_usage("/boot").free:
        raise RuntimeError("candidate UKI does not fit EFI with a 16 MiB reserve")
    disk, partition = disk_partition()
    before_entries = run(["/usr/bin/efibootmgr", "-v"])
    if LOADER.lower() in before_entries.lower() or LABEL in before_entries:
        raise RuntimeError("candidate UEFI loader or label already registered")
    before_ids = entry_ids(before_entries)
    before_hashes = SNAPSHOT.boot_hashes()
    temp = DEST.parent / (DEST.name + ".staging-" + str(os.getpid()))
    entry = None
    copied = False
    try:
        with image.open("rb") as src, temp.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=4 * 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if UKI.digest(temp) != stage["checks"]["image_sha256"] or DEST.exists():
            raise RuntimeError("EFI copy changed or destination was claimed")
        os.replace(temp, DEST)
        copied = True
        run(["/usr/bin/efibootmgr", "-C", "-d", str(disk), "-p", partition,
             "-L", LABEL, "-l", LOADER])
        entries = run(["/usr/bin/efibootmgr", "-v"])
        created = entry_ids(entries) - before_ids
        if len(created) != 1:
            raise RuntimeError("cannot identify exactly one new UEFI entry")
        new_entry = created.pop().upper()
        line = next((line for line in entries.splitlines()
                     if re.match(r"^Boot" + new_entry + r"\*?\s", line)), "")
        if not line.startswith("Boot" + new_entry + "*") or \
                LABEL not in line or LOADER.lower() not in line.lower():
            raise RuntimeError("new UEFI entry does not point at the candidate image")
        entry = new_entry
        after = SNAPSHOT.plan()
        hashes = SNAPSHOT.boot_hashes()
        expected_hashes = before_hashes | {str(DEST.relative_to("/boot")):
                                           stage["checks"]["image_sha256"]}
        if after["boot"] != state["boot"] or after["packages"] != state["packages"] or \
                after["boot_id"] != state["boot_id"] or hashes != expected_hashes:
            raise RuntimeError("rollback files, packages or BootOrder changed during EFI staging")
        record = {"captured_at": datetime.now(timezone.utc).isoformat(),
                  "pass": True, "candidate_subvolume": "@nvidia620",
                  "candidate_id": stage["candidate_id"],
                  "image": str(DEST), "image_sha256": stage["checks"]["image_sha256"],
                  "audio_root_profile": profile, "entry": entry, "label": LABEL,
                  "loader": LOADER, "boot_before": state["boot"],
                  "boot_after": after["boot"], "efi_sha256_before": before_hashes,
                  "efi_sha256_after": hashes, "live_packages_unchanged": True,
                  "boot_next_set": False, "reboot_executed": False,
                  "hardware_qualified": False}
        with receipt_tmp.open("x") as dst:
            dst.write(json.dumps(record, indent=2) + "\n")
            dst.flush()
            os.fsync(dst.fileno())
        owner = os.environ.get("PKEXEC_UID", "")
        if owner.isdecimal() and int(owner) > 0:
            os.chown(receipt_tmp, int(owner), -1)
        if output.exists():
            raise RuntimeError("receipt path was claimed during EFI staging")
        os.replace(receipt_tmp, output)
    except Exception as error:
        # A failed create-only stage must not leave a candidate in the normal
        # boot path. If entry cleanup cannot be proved, retain its EFI file.
        cleanup_errors = []
        remaining = None
        try:
            current_entries = run(["/usr/bin/efibootmgr", "-v"])
            new_ids = entry_ids(current_entries) - before_ids
            if entry is None and len(new_ids) == 1:
                new_entry = next(iter(new_ids)).upper()
                line = next((line for line in current_entries.splitlines()
                             if re.match(r"^Boot" + new_entry + r"\*?\s", line)), "")
                if LABEL in line and LOADER.lower() in line.lower():
                    entry = new_entry
            if entry is not None:
                run(["/usr/bin/efibootmgr", "-b", entry, "-B"])
            remaining = entry_ids(run(["/usr/bin/efibootmgr", "-v"])) - before_ids
            if remaining:
                cleanup_errors.append("new UEFI entries remain: " + ",".join(sorted(remaining)))
        except Exception as cleanup_error:
            cleanup_errors.append("entry cleanup: " + str(cleanup_error))
        try:
            restore_boot_order(state["boot"])
        except Exception as cleanup_error:
            cleanup_errors.append("BootOrder restore: " + str(cleanup_error))
        if copied and remaining == set():
            DEST.unlink()
        if cleanup_errors:
            raise RuntimeError(str(error) + "; " + "; ".join(cleanup_errors)) from error
        raise
    finally:
        temp.unlink(missing_ok=True)
        receipt_tmp.unlink(missing_ok=True)
    print(json.dumps({"pass": True, "entry": entry,
                      "boot_order_unchanged": True, "boot_next_set": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
