#!/usr/bin/env python3
"""Preflight the signed 620 archives and kernel38 modules without installation."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "7.2.8-38-rtx-spark-npu"
PACKAGES = {
    "nvidia-utils": (
        ROOT / "build/nvidia620-packages/nvidia-utils-620.70.06-1-aarch64.pkg.tar.xz",
        "bc4b8afd35bc14b963b4a2d5d123a76ca72bba3d56c8237ae44b1439ac2bd3da"),
    "nvidia-open-dkms": (
        ROOT / "build/nvidia620-packages/nvidia-open-dkms-620.70.06-1-aarch64.pkg.tar.xz",
        "e333f8744caa175bccca649b165ff5a31c94de6b7ca573364a0106231351af92"),
    "n1x-nvidia-drm-fix-620": (
        ROOT / "build/nvidia620-packages/n1x-nvidia-drm-fix-620-620.70.06-1-any.pkg.tar.xz",
        "23b3ef76307ab1668a2a6666f081a7e5a52e9f1af25708ffd2d89ab90e10e023"),
    "linux-p16-platform-38-drivers-nvidia620": (
        ROOT / "build/uvc-kernel38-drivers620-package-20261118/"
        "linux-p16-platform-38-drivers-nvidia620-7.2.8-38-aarch64.pkg.tar.xz",
        "2f669e17dc68f4f3227c1e9e2a4c54405c8e54c72eeb2bc4d89982cdb77a6232"),
}


def run(command, timeout=90):
    return subprocess.run(command, check=True, capture_output=True,
                          text=True, timeout=timeout)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pkginfo(path):
    output = run(["/usr/bin/bsdtar", "-xOf", str(path), ".PKGINFO"],
                 timeout=90).stdout
    result = {}
    for line in output.splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            result.setdefault(key, []).append(value)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    inputs = {}
    for name, (path, expected) in PACKAGES.items():
        actual = sha256(path)
        info = pkginfo(path)
        inputs[name] = {"path": str(path.relative_to(ROOT)),
                        "sha256": actual,
                        "sha256_expected": expected,
                        "sha256_match": actual == expected,
                        "package_name": info.get("pkgname", [None])[0],
                        "package_version": info.get("pkgver", [None])[0],
                        "dependencies": info.get("depend", [])}
    with tempfile.TemporaryDirectory(prefix="p16-nvidia620-preflight-") as folder:
        temp = Path(folder)
        keyring = temp / "archlinuxarm.gpg"
        run(["/usr/bin/gpg", "--dearmor", "--output", str(keyring),
             "/usr/share/pacman/keyrings/archlinuxarm.gpg"])
        for name in ("nvidia-utils", "nvidia-open-dkms"):
            path = PACKAGES[name][0]
            verified = run(["/usr/bin/gpgv", "--keyring", str(keyring),
                            str(path) + ".sig", str(path)])
            inputs[name]["signed_by_archlinuxarm_build_system"] = (
                "Good signature from \"Arch Linux ARM Build System" in
                verified.stderr)
        extracted = temp / "drivers"
        extracted.mkdir()
        run(["/usr/bin/bsdtar", "-xf", str(PACKAGES[
            "linux-p16-platform-38-drivers-nvidia620"][0]), "-C",
            str(extracted)])
        modules_dir = extracted / "usr/lib/modules" / RELEASE
        modules = sorted(modules_dir.rglob("*.ko"))
        versions = {path.name: run(["/usr/bin/modinfo", "-F", "version",
                                    str(path)]).stdout.strip()
                    for path in modules if path.name.startswith("nvidia")}
        vermagic = {path.name: run(["/usr/bin/modinfo", "-F", "vermagic",
                                     str(path)]).stdout.strip()
                    for path in modules}
        kernel_dir = Path("/usr/lib/modules") / RELEASE
        btf = json.loads(run([
            "/usr/bin/python3", str(ROOT / "scripts/verify-module-btf.py"),
            "--vmlinux", str(kernel_dir / "build/vmlinux"),
            "--kernel-image", str(kernel_dir / "vmlinuz"),
            "--module-dir", str(modules_dir)], timeout=120).stdout)
    boot = Path("/boot")
    statfs = os.statvfs(boot)
    boot_free = statfs.f_bavail * statfs.f_frsize
    running_utils = run(["/usr/bin/pacman", "-Q", "nvidia-utils"]).stdout.strip()
    boot_order = next((line for line in run(["/usr/bin/efibootmgr"]).stdout.splitlines()
                       if line.startswith("BootOrder:")), None)
    expected_dependencies = {
        "nvidia-open-dkms": "nvidia-utils=620.70.06",
        "n1x-nvidia-drm-fix-620": "nvidia-open-dkms=620.70.06",
        "linux-p16-platform-38-drivers-nvidia620": "nvidia-utils=620.70.06",
    }
    dependency_match = all(required in inputs[name]["dependencies"]
                           for name, required in expected_dependencies.items())
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "running_kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "running_nvidia_utils": running_utils,
        "boot_order": boot_order,
        "efi_free_bytes": boot_free,
        "packages": inputs,
        "versioned_dependencies_match": dependency_match,
        "driver_module_count": len(modules),
        "nvidia_module_versions": versions,
        "module_vermagic": vermagic,
        "btf": btf,
    }
    result["pass"] = (
        all(item["sha256_match"] and item["package_name"] == name
            for name, item in inputs.items()) and
        inputs["nvidia-utils"]["package_version"] == "620.70.06-1" and
        inputs["nvidia-open-dkms"]["package_version"] == "620.70.06-1" and
        inputs["nvidia-utils"]["signed_by_archlinuxarm_build_system"] and
        inputs["nvidia-open-dkms"]["signed_by_archlinuxarm_build_system"] and
        dependency_match and len(modules) == 13 and len(versions) == 5 and
        all(version == "620.70.06" for version in versions.values()) and
        all(value.startswith(RELEASE + " ") for value in vermagic.values()) and
        btf["modules_checked"] == btf["modules_with_btf"] == 13 and
        boot_free >= 250 * 1024 * 1024 and
        running_utils.startswith("nvidia-utils 615.78.08-") and
        result["running_kernel"] == RELEASE)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"],
                      "driver_module_count": len(modules),
                      "btf_modules": btf["modules_with_btf"],
                      "efi_free_bytes": boot_free}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
