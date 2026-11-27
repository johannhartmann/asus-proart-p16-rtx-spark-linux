#!/usr/bin/env python3
"""Add the verified N1X 620 test image to Limine's menu."""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from importlib.util import module_from_spec, spec_from_file_location


SPEC = spec_from_file_location("p16_nvidia620_efi", Path(__file__).with_name("stage-nvidia620-efi.py"))
EFI = module_from_spec(SPEC)
SPEC.loader.exec_module(EFI)

BOOT = Path("/boot")
MENU = BOOT / "limine.conf"
TITLE = "P16 NVIDIA 620 Test"


def install(stage_dir, receipt_path):
    stage, _, _ = EFI.validate_stage(stage_dir)
    expected = stage["checks"]["image_sha256"]
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("pass") is not True or receipt.get("candidate_subvolume") != "@nvidia620"
            or receipt.get("candidate_id") != stage["candidate_id"]
            or receipt.get("image_sha256") != expected or receipt.get("image") != str(EFI.DEST)):
        raise ValueError("EFI receipt does not describe the verified candidate")

    image = EFI.DEST.read_bytes()
    if hashlib.sha256(image).hexdigest() != expected:
        raise ValueError("Installed candidate image hash differs from its receipt")
    state = EFI.SNAPSHOT.plan()
    EFI.verify_candidate_root(state, stage, EFI.DEST)
    efi_directory = BOOT / "EFI"
    possible_shadows = {
        "efi/limine/limine.conf", "efi/boot/limine.conf",
        "boot/limine/limine.conf", "boot/limine.conf", "limine/limine.conf",
    }
    for path in BOOT.rglob("limine.conf"):
        if path.relative_to(BOOT).as_posix().lower() in possible_shadows:
            raise ValueError(f"Another Limine configuration can shadow {MENU}: {path}")
    if not efi_directory.is_dir():
        raise ValueError("EFI directory is missing")

    original = MENU.read_bytes()
    pin = hashlib.blake2b(image).hexdigest()
    entry = (f"/{TITLE}\n    protocol: efi\n"
             "    comment: One-time test of 620.70.06 in @nvidia620\n"
             f"    path: boot():/{EFI.DEST.relative_to(BOOT)}#{pin}\n").encode()
    if re.search(rb"(?m)^/\+?" + re.escape(TITLE.encode()) + rb"\s*$", original):
        if original.endswith(entry):
            EFI.UKI.BOOT.verify_menu(MENU, BOOT, acpi_mode="auto")
            return {"entry": TITLE, "already_present": True}
        raise ValueError("A Limine entry with that title already exists")

    updated = original + (b"\n" if original.endswith(b"\n") else b"\n\n") + entry
    staged = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".limine-nvidia620-", dir=BOOT, delete=False) as stream:
            staged = Path(stream.name)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        EFI.UKI.BOOT.verify_menu(staged, BOOT, acpi_mode="auto")
        if MENU.read_bytes() != original or EFI.UKI.digest(EFI.DEST) != expected:
            raise ValueError("Boot files changed during validation")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = BOOT / f"limine.conf.before-nvidia620-{stamp}"
        with backup.open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, MENU)
        directory_fd = os.open(BOOT, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if MENU.read_bytes() != updated:
            raise RuntimeError(f"Published menu differs from validated bytes. Backup: {backup}")
        return {"entry": TITLE, "image": str(EFI.DEST), "image_sha256": expected,
                "default": re.search(rb"(?m)^default_entry: *(.*)$", original)[1].decode(),
                "backup": str(backup)}
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uki-stage-dir", required=True, type=Path)
    parser.add_argument("--efi-receipt", required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run through graphical Polkit as root")
    try:
        with Path("/run/lock/boot-partition.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            print(json.dumps(install(args.uki_stage_dir, args.efi_receipt), indent=2))
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
