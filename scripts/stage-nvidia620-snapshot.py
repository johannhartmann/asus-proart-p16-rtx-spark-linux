#!/usr/bin/env python3
"""Prepare or create the isolated @nvidia620 Btrfs snapshot without boot changes.

The default plan is read-only. --stage requires graphical Polkit root access,
refuses a concurrent package transaction and never touches EFI or BootNext.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


EXPECTED_ROOT = "@"
TARGET = "@nvidia620"
EXPECTED_KERNEL = "7.2.8-38-rtx-spark-npu"


def run(command, *, timeout=30):
    return subprocess.run(command, capture_output=True, text=True,
                          check=True, timeout=timeout)


def root_mount():
    entries = json.loads(run(["/usr/bin/findmnt", "-J", "-o",
                              "SOURCE,FSTYPE,UUID,OPTIONS", "/"]).stdout)["filesystems"]
    if len(entries) != 1:
        raise RuntimeError("expected exactly one root mount")
    entry = entries[0]
    options = entry["options"].split(",")
    if entry["fstype"] != "btrfs" or "subvol=/@" not in options:
        raise RuntimeError("live root is not the expected Btrfs @ subvolume")
    source = entry["source"].split("[", 1)[0]
    if not source.startswith("/dev/") or not Path(source).exists():
        raise RuntimeError("unexpected Btrfs block device")
    return {"device": source, "uuid": entry["uuid"],
            "subvolume": EXPECTED_ROOT, "source": entry["source"]}


def package_versions():
    result = run(["/usr/bin/pacman", "-Q", "nvidia-utils", "nvidia-open-dkms",
                  "n1x-nvidia-drm-fix", "linux-p16-platform-38-drivers"])
    return dict(line.split(" ", 1) for line in result.stdout.splitlines())


def pending_pacman_auth():
    result = run(["/usr/bin/ps", "-eo", "comm=,args="])
    return [line.strip() for line in result.stdout.splitlines()
            if line.lstrip().startswith("pkexec ") and
            " /usr/bin/pacman " in line]


def boot_state():
    output = run(["/usr/bin/efibootmgr"]).stdout
    return {key: next((line for line in output.splitlines()
                       if line.startswith(key + ":")), None)
            for key in ("BootCurrent", "BootOrder", "BootNext")}


def boot_hashes():
    root = Path("/boot")
    files = sorted(path for path in root.rglob("*.efi") if path.is_file())
    result = {}
    for path in files:
        hash_ = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
                hash_.update(block)
        result[str(path.relative_to(root))] = hash_.hexdigest()
    return result


def snapshot_id(path):
    output = run(["/usr/bin/btrfs", "subvolume", "show", str(path)]).stdout
    match = re.search(r"^\s*Subvolume ID:\s*(\d+)\s*$", output, re.MULTILINE)
    if not match:
        raise RuntimeError("could not read Btrfs subvolume ID")
    return int(match.group(1))


def clear_candidate_db_lock(target):
    # The host lock protects the snapshot operation, but its copied inode
    # must not block later Pacman work inside the candidate.
    candidate_lock = target / "var/lib/pacman/db.lck"
    if not candidate_lock.is_file():
        raise RuntimeError("snapshot did not contain the expected host Pacman lock")
    candidate_lock.unlink()
    if candidate_lock.exists():
        raise RuntimeError("candidate Pacman lock removal failed")


def plan():
    mount = root_mount()
    packages = package_versions()
    kernel = Path("/proc/sys/kernel/osrelease").read_text().strip()
    running_driver = run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                          "--format=csv,noheader"]).stdout.strip()
    pending = pending_pacman_auth()
    db_locked = Path("/var/lib/pacman/db.lck").exists()
    boot = boot_state()
    boot_mount = run(["/usr/bin/findmnt", "-n", "-o", "FSTYPE", "/boot"]).stdout.strip()
    ready = (kernel == EXPECTED_KERNEL and
             packages.get("nvidia-utils", "").startswith("615.") and
             packages.get("nvidia-open-dkms", "").startswith("615.") and
             packages.get("n1x-nvidia-drm-fix", "").startswith("615.") and
             packages.get("linux-p16-platform-38-drivers", "").startswith("7.2.8-38") and
             running_driver == "615.78.08" and
             not pending and not db_locked and
             boot_mount == "vfat" and
             boot["BootOrder"] is not None and
             boot["BootOrder"].split(":", 1)[1].strip().startswith("0002,"))
    return {"captured_at": datetime.now(timezone.utc).isoformat(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "kernel": kernel, "running_nvidia_driver": running_driver,
            "mount": mount, "packages": packages,
            "boot": boot, "pending_pacman_auth": pending,
            "boot_filesystem": boot_mount,
            "pacman_database_locked": db_locked, "ready_to_stage": ready,
            "target_subvolume": TARGET,
            "no_reboot_or_boot_entry_change": True}


def stage(state, output):
    if os.geteuid() != 0:
        raise RuntimeError("--stage requires root through graphical Polkit")
    if not state["ready_to_stage"]:
        raise RuntimeError("plan preflight is not ready; resolve package/auth state first")
    if output.exists():
        raise RuntimeError("choose a new output manifest")
    before_boot_files = boot_hashes()
    if not before_boot_files:
        raise RuntimeError("no readable EFI files under /boot")
    before_boot = state["boot"]
    before_packages = state["packages"]
    lock = Path("/var/lib/pacman/db.lck")
    lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    lock_inode = os.fstat(lock_fd).st_ino
    os.write(lock_fd, (str(os.getpid()) + "\n").encode())
    created = False
    try:
        if pending_pacman_auth() or package_versions() != before_packages:
            raise RuntimeError("package state changed after preflight")
        folder = Path(tempfile.mkdtemp(prefix="p16-nvidia620-snapshot-", dir="/run"))
        top = folder / "top"
        top.mkdir(mode=0o700)
        mounted = False
        try:
            run(["/usr/bin/mount", "-t", "btrfs", "-o", "subvolid=5",
                 state["mount"]["device"], str(top)])
            mounted = True
            source, target = top / EXPECTED_ROOT, top / TARGET
            if not source.is_dir() or target.exists():
                raise RuntimeError("source @ missing or @nvidia620 already exists")
            source_id = snapshot_id(source)
            if source_id != 256:
                raise RuntimeError(f"unexpected live @ subvolume ID: {source_id}")
            run(["/usr/bin/btrfs", "subvolume", "snapshot", str(source),
                 str(target)], timeout=60)
            created = True
            target_id = snapshot_id(target)
            if target_id == source_id or not (target / "var/lib/pacman/local").is_dir():
                raise RuntimeError("snapshot ID/database verification failed")
            clear_candidate_db_lock(target)
        finally:
            if mounted:
                # Never recursively clean a mountpoint if unmounting fails.
                run(["/usr/bin/umount", str(top)])
            top.rmdir()
            folder.rmdir()
    finally:
        os.close(lock_fd)
        if lock.stat().st_ino != lock_inode:
            raise RuntimeError("pacman lock was replaced; refusing to remove it")
        lock.unlink()
    after = plan()
    after_boot_files = boot_hashes()
    passed = (created and target_id != 256 and
              before_boot == after["boot"] and
              before_packages == after["packages"] and
              before_boot_files == after_boot_files and
              state["boot_id"] == after["boot_id"])
    receipt = {"status": "pass" if passed else "fail",
               "source_subvolume": "@", "source_id": source_id,
               "candidate_subvolume": TARGET, "candidate_id": target_id,
               "before": state, "after": after,
               "efi_file_sha256_before": before_boot_files,
               "efi_file_sha256_after": after_boot_files,
               "package_transaction_executed": False,
               "candidate_pacman_lock_removed": True,
               "boot_entry_created": False, "reboot_executed": False,
               "next_gate": "mount @nvidia620 privately, perform the isolated 620 package transaction and build/verify its distinct UKI"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "candidate_id": target_id,
                      "boot_unchanged": before_boot_files == after_boot_files}))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--output", type=Path,
                        help="new receipt path, required with --stage")
    args = parser.parse_args()
    if args.stage and args.output is None:
        parser.error("--stage requires --output")
    state = plan()
    if not args.stage:
        print(json.dumps(state, indent=2))
        return 0
    return stage(state, args.output)


if __name__ == "__main__":
    sys.exit(main())
