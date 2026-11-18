#!/usr/bin/env python3
"""Build and verify a kernel38/620 UKI in @nvidia620, without touching EFI.

Run only after stage-nvidia620-packages.py has produced a passing receipt.
The candidate root is mounted privately; mkinitcpio runs in that root with
post hooks disabled and writes its image into a temporary bind mount in /run.
Only a verified image and receipt are copied to a new non-EFI output directory.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
RELEASE = "7.2.8-38-rtx-spark-npu"
SOURCE_UKI = Path("/boot/EFI/Linux/omarchy_linux-p16-platform-38.efi")
GUEST_WORK = Path("/run/p16-nvidia620-uki")


def sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SNAPSHOT = sibling("p16_nvidia620_snapshot", "stage-nvidia620-snapshot.py")
PACKAGES = sibling("p16_nvidia620_packages", "stage-nvidia620-packages.py")
PREPARE = sibling("p16_nvidia620_cmdline", "prepare-nvidia620-cmdline.py")
BOOT = PREPARE.DSP.BOOT


def run(command, *, timeout=120, cwd=None):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}: "
                           + result.stderr[-1800:] + result.stdout[-500:])
    return result


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def receipt(path):
    record = json.loads(path.read_text())
    if record.get("pass") is not True or record.get("candidate_subvolume") != SNAPSHOT.TARGET:
        raise RuntimeError("candidate package receipt did not pass")
    if not isinstance(record.get("candidate_id"), int) or record["candidate_id"] == 256:
        raise RuntimeError("candidate package receipt has no distinct subvolume ID")
    if record.get("live_packages_before") != record.get("live_packages_after") or \
            record.get("boot_before") != record.get("boot_after") or \
            record.get("efi_sha256_before") != record.get("efi_sha256_after"):
        raise RuntimeError("package staging receipt does not preserve rollback state")
    return record


def candidate_versions(root):
    result = run(["/usr/bin/pacman", "--sysroot", str(root), "-Q",
                  *PACKAGES.SIM.EXPECTED])
    versions = dict(line.split(" ", 1) for line in result.stdout.splitlines())
    if versions != PACKAGES.SIM.EXPECTED:
        raise RuntimeError("candidate root does not contain the exact 620 package set")
    return versions


def verify_embedded_nvidia(image, root, work):
    initrd = work / "initrd"
    run(["/usr/bin/objcopy", "--dump-section", f".initrd={initrd}",
         str(image), str(work / "discard.efi")], timeout=90)
    extracted = work / "extracted"
    extracted.mkdir()
    run(["/usr/bin/lsinitcpio", "-x", str(initrd)], cwd=extracted, timeout=180)
    result = {}
    for name in ("nvidia", "nvidia-modeset", "nvidia-uvm", "nvidia-drm"):
        matches = list((extracted / "usr/lib/modules" / RELEASE).rglob(name + ".ko*"))
        installed = list((root / "usr/lib/modules" / RELEASE).rglob(name + ".ko*"))
        if len(matches) != 1 or len(installed) != 1:
            raise RuntimeError(f"expected one embedded and installed {name} module")
        version = run(["/usr/bin/modinfo", "-F", "version", str(matches[0])]).stdout.strip()
        vermagic = run(["/usr/bin/modinfo", "-F", "vermagic", str(matches[0])]).stdout.split()
        if version != "620.70.06" or not vermagic or vermagic[0] != RELEASE:
            raise RuntimeError(f"embedded {name} version/ABI does not match 620 kernel38")
        result[name] = {"version": version, "vermagic": vermagic[0],
                        "embedded_sha256": digest(matches[0]),
                        "installed_sha256": digest(installed[0])}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-uki", type=Path, default=SOURCE_UKI)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run through graphical Polkit as root")
    output = args.output_dir.resolve()
    if output.exists() or output.is_relative_to(Path("/boot")) or \
            output.is_relative_to(Path("/efi")) or output.is_relative_to(Path("/run")):
        parser.error("choose a new durable output directory outside EFI and /run")
    package_record = receipt(args.package_receipt)
    state = SNAPSHOT.plan()
    if not state["ready_to_stage"] or state["boot"]["BootNext"] is not None:
        raise RuntimeError("live package/boot preflight is not ready")
    if state["packages"] != package_record["live_packages_after"] or \
            state["boot"] != package_record["boot_after"]:
        raise RuntimeError("live rollback state differs from package receipt")
    before_efi = SNAPSHOT.boot_hashes()
    if not before_efi or before_efi != package_record["efi_sha256_after"]:
        raise RuntimeError("EFI files changed after candidate package staging")
    source = args.source_uki.resolve(strict=True)
    if not source.is_relative_to(Path("/boot/EFI/Linux")):
        raise RuntimeError("source UKI must be an existing EFI/Linux image")
    source_hash = digest(source)
    sections = BOOT.sections(source)
    if sections[".uname"].rstrip(b"\0\n").decode() != RELEASE:
        raise RuntimeError("source UKI is not kernel38")
    cmdline = PREPARE.rewrite(sections[".cmdline"].rstrip(b"\0\n").decode(),
                              RELEASE, SNAPSHOT.TARGET).strip()
    run(["/usr/bin/p16-platform-update-check", "--release", RELEASE,
         "--image", str(source)], timeout=300)
    # A failed unmount must leave the private directory intact for inspection.
    # TemporaryDirectory would recursively walk the mounted candidate root.
    work = Path(tempfile.mkdtemp(prefix="p16-nvidia620-uki-", dir="/run"))
    mounted = []
    guest_shared = None
    try:
        candidate = work / "candidate"
        shared = work / "shared"
        candidate.mkdir(mode=0o700)
        shared.mkdir(mode=0o700)
        (shared / "cmdline").write_text(cmdline + "\n")
        checks = {}
        try:
            run(["/usr/bin/mount", "-t", "btrfs", "-o",
                 f"subvol={SNAPSHOT.TARGET}", state["mount"]["device"], str(candidate)])
            mounted.append(candidate)
            if SNAPSHOT.snapshot_id(candidate) != package_record["candidate_id"]:
                raise RuntimeError("candidate subvolume differs from package receipt")
            boot_mount = subprocess.run(
                ["/usr/bin/findmnt", "-M", str(candidate / "boot")],
                capture_output=True, timeout=20)
            if boot_mount.returncode != 1:
                raise RuntimeError("candidate /boot is mounted or its mount state is unknown")
            checks["candidate_packages"] = candidate_versions(candidate)
            guest_shared = candidate / GUEST_WORK.relative_to("/")
            guest_shared.mkdir(parents=True, mode=0o700, exist_ok=False)
            for host, guest in (("/proc", candidate / "proc"),
                                ("/sys", candidate / "sys"),
                                ("/dev", candidate / "dev"),
                                (str(shared), guest_shared)):
                run(["/usr/bin/mount", "--bind", host, str(guest)])
                mounted.append(guest)
            guest_image = GUEST_WORK / "candidate.efi"
            build = run(["/usr/bin/chroot", str(candidate), "/usr/bin/mkinitcpio",
                         "--nopost", "-k", RELEASE,
                         "--kernelimage", f"/usr/lib/modules/{RELEASE}/vmlinuz",
                         "--cmdline", str(GUEST_WORK / "cmdline"),
                         "--uki", str(guest_image)], timeout=420)
            checks["mkinitcpio_stdout_tail"] = build.stdout[-1500:]
            image = shared / "candidate.efi"
            if not image.is_file() or image.stat().st_size == 0:
                raise RuntimeError("mkinitcpio did not produce a candidate UKI")
            verification = run(["/usr/bin/chroot", str(candidate),
                                "/usr/bin/p16-platform-update-check", "--release",
                                RELEASE, "--image", str(guest_image)], timeout=420)
            checks["platform_verifier"] = verification.stdout.strip()
            guest_sections = BOOT.sections(image)
            actual_cmdline = guest_sections[".cmdline"].rstrip(b"\0\n").decode()
            # mkinitcpio appends harmless whitespace while joining cmdline
            # lines; preserve and compare the exact ordered argument text.
            if actual_cmdline.strip() != cmdline or \
                    guest_sections[".linux"][:len(sections[".linux"])] != sections[".linux"]:
                raise RuntimeError("candidate UKI changed kernel or command line")
            dsp = PREPARE.DSP.check_cmdline(actual_cmdline, RELEASE, RELEASE,
                                            SNAPSHOT.TARGET, str(image))
            if not dsp["pass"]:
                raise RuntimeError("candidate UKI audio/root command line failed")
            checks["dsp_root_cmdline"] = dsp
            checks["embedded_nvidia"] = verify_embedded_nvidia(image, candidate, work)
            checks["image_bytes"] = image.stat().st_size
            checks["image_sha256"] = digest(image)
            checks["efi_free_bytes"] = shutil.disk_usage("/boot").free
            if checks["image_bytes"] + 16 * 1024 * 1024 > checks["efi_free_bytes"]:
                raise RuntimeError("candidate UKI does not fit EFI with a 16 MiB reserve")
        finally:
            cleanup_error = None
            while mounted:
                target = mounted[-1]
                try:
                    run(["/usr/bin/umount", str(target)], timeout=45)
                    mounted.pop()
                    if target == guest_shared:
                        guest_shared.rmdir()
                except Exception as error:
                    cleanup_error = str(error)
                    break
            if cleanup_error:
                raise RuntimeError("private candidate mount cleanup failed: " + cleanup_error)
        after = SNAPSHOT.plan()
        if state["boot"] != after["boot"] or state["packages"] != after["packages"] or \
                state["boot_id"] != after["boot_id"] or before_efi != SNAPSHOT.boot_hashes() or \
                digest(source) != source_hash:
            raise RuntimeError("live rollback state changed during UKI build")
        output.mkdir(parents=True, mode=0o700)
        shutil.copy2(shared / "candidate.efi", output / "kernel38-nvidia620.efi")
        if digest(output / "kernel38-nvidia620.efi") != checks["image_sha256"]:
            raise RuntimeError("published candidate UKI differs from verified build")
        record = {"captured_at": datetime.now(timezone.utc).isoformat(),
                  "pass": True, "candidate_subvolume": SNAPSHOT.TARGET,
                  "candidate_id": package_record["candidate_id"],
                  "package_receipt": str(args.package_receipt),
                  "source_uki": str(source), "source_uki_sha256": source_hash,
                  "checks": checks, "efi_sha256_before": before_efi,
                  "efi_sha256_after": SNAPSHOT.boot_hashes(),
                  "boot_before": state["boot"], "boot_after": after["boot"],
                  "live_packages_before": state["packages"],
                  "live_packages_after": after["packages"],
                  "boot_files_written": False, "boot_entry_created": False,
                  "reboot_executed": False, "hardware_qualified": False}
        (output / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
        owner = os.environ.get("PKEXEC_UID", "")
        if owner.isdecimal() and int(owner) > 0:
            for path in (output, output / "kernel38-nvidia620.efi", output / "manifest.json"):
                os.chown(path, int(owner), -1)
        print(json.dumps({"pass": True, "image": str(output / "kernel38-nvidia620.efi"),
                          "sha256": checks["image_sha256"], "boot_files_written": False}))
    finally:
        if not mounted:
            shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
