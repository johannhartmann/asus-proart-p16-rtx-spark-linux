#!/usr/bin/env python3
"""Audit 620 archive paths against live Pacman ownership without installation."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = {
    "nvidia-utils": ("build/nvidia620-packages/nvidia-utils-620.70.06-1-aarch64.pkg.tar.xz",
                     "bc4b8afd35bc14b963b4a2d5d123a76ca72bba3d56c8237ae44b1439ac2bd3da"),
    "nvidia-open-dkms": ("build/nvidia620-packages/nvidia-open-dkms-620.70.06-1-aarch64.pkg.tar.xz",
                         "e333f8744caa175bccca649b165ff5a31c94de6b7ca573364a0106231351af92"),
    "n1x-nvidia-drm-fix-620": ("build/nvidia620-packages/n1x-nvidia-drm-fix-620-620.70.06-1-any.pkg.tar.xz",
                                "23b3ef76307ab1668a2a6666f081a7e5a52e9f1af25708ffd2d89ab90e10e023"),
    "linux-p16-platform-38-drivers-nvidia620": (
        "build/uvc-kernel38-drivers620-package-20261118/linux-p16-platform-38-drivers-nvidia620-7.2.8-38-aarch64.pkg.tar.xz",
        "2f669e17dc68f4f3227c1e9e2a4c54405c8e54c72eeb2bc4d89982cdb77a6232"),
}
REPLACED = {"nvidia-utils", "nvidia-open-dkms", "n1x-nvidia-drm-fix",
            "linux-p16-platform-34-drivers", "linux-p16-platform-36-drivers",
            "linux-p16-platform-37-drivers", "linux-p16-platform-38-drivers"}


def digest(path):
    hash_ = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            hash_.update(block)
    return hash_.hexdigest()


def field(text, name):
    marker = f"%{name}%\n"
    return text.split(marker, 1)[1].split("\n", 1)[0] if marker in text else None


def local_owners():
    owners = {}
    package_count = 0
    for directory in Path("/var/lib/pacman/local").iterdir():
        files = directory / "files"
        description = directory / "desc"
        if not files.is_file() or not description.is_file():
            continue
        package = field(description.read_text(errors="replace"), "NAME")
        if not package:
            raise RuntimeError(f"missing local package name in {directory}")
        package_count += 1
        content = files.read_text(errors="replace")
        if not content:
            continue
        section = content.split("%FILES%\n", 1)
        if len(section) != 2:
            raise RuntimeError(f"missing file list in {directory}")
        for relative in section[1].split("\n%", 1)[0].splitlines():
            if relative and not relative.endswith("/"):
                owners.setdefault(relative, set()).add(package)
    return owners, package_count


def archive_files(path):
    result = subprocess.run(["/usr/bin/bsdtar", "-tf", str(path)],
                            capture_output=True, text=True, check=True, timeout=60)
    paths = set()
    for member in result.stdout.splitlines():
        name = member.removeprefix("./")
        if name and not name.endswith("/") and not name.startswith("."):
            paths.add(name)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    owners, package_count = local_owners()
    proposed = {}
    archives = {}
    for package, (relative, expected) in ARCHIVES.items():
        path = ROOT / relative
        actual = digest(path)
        if actual != expected:
            raise RuntimeError(f"archive hash mismatch: {relative}")
        paths = archive_files(path)
        archives[package] = {"path": relative, "sha256": actual,
                             "file_count": len(paths)}
        for name in paths:
            proposed.setdefault(name, set()).add(package)
    cross_package = {name: sorted(packages) for name, packages in proposed.items()
                     if len(packages) > 1}
    unexpected_owned = {name: sorted(owners[name]) for name in proposed
                        if name in owners and not owners[name] <= REPLACED}
    unowned_present = sorted(name for name in proposed if name not in owners
                             and os.path.lexists("/" + name))
    expected_replacements = {name: sorted(owners[name]) for name in proposed
                             if name in owners and owners[name] <= REPLACED}
    passed = not (cross_package or unexpected_owned or unowned_present)
    report = {"captured_at": datetime.now(timezone.utc).isoformat(),
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "installed_package_count": package_count,
              "new_archive_inputs": archives,
              "unique_proposed_file_count": len(proposed),
              "expected_replaced_file_count": len(expected_replacements),
              "expected_replaced_owner_counts": {package: sum(package in old for old in
                  expected_replacements.values()) for package in sorted(REPLACED)},
              "cross_new_package_collisions": cross_package,
              "unexpected_installed_owner_collisions": unexpected_owned,
              "unowned_existing_file_collisions": unowned_present,
              "pass": passed,
              "limit": "Path/ownership preflight only; actual package extraction, ALPM hooks, initramfs, module behavior and boot are not tested."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": passed, "unique_files": len(proposed),
                      "expected_replacements": len(expected_replacements),
                      "cross_package": len(cross_package),
                      "unexpected_owned": len(unexpected_owned),
                      "unowned_existing": len(unowned_present)}))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
