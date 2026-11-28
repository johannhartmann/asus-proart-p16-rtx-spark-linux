#!/usr/bin/env python3
"""Stage and build the P16 external drivers for the Omarchy 7.3.6 port."""

import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

from prepare import KERNEL_RELEASE, REPO, apply_patch, recipe_patches, sha256, verify

NVIDIA_HASH = "e333f8744caa175bccca649b165ff5a31c94de6b7ca573364a0106231351af92"
NVIDIA_VERSION = "620.70.06"
PLATFORM = {
    "dsp": "n1x_adsp",
    "pluton": "n1x_pluton",
    "scp": "n1x_scp",
    "hwmon": "spbm",
    "provider/driver": "n1x_npu_bootstrap",
}
NVIDIA = ("nvidia", "nvidia-drm", "nvidia-modeset", "nvidia-uvm", "nvidia-peermem")


def stage(recipe, nvidia_archive, hwmon_repo, output):
    verify(nvidia_archive, NVIDIA_HASH)
    _, omarchy_patches = recipe_patches(recipe, None)
    spec = importlib.util.spec_from_file_location(
        "p16_modules", REPO / "scripts/prepare-platform-candidate.py")
    reusable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reusable)

    output.mkdir(parents=True)
    recorded = {}
    for kind in ("dsp", "pluton", "scp"):
        for name in reusable.FILES[kind]:
            relative = Path(kind) / name
            reusable.copy_input(REPO / "platform" / relative, output / relative,
                                recorded, output)
    reusable.copy_input(REPO / "platform/dsp/afe/mt8901-afe-sram.h",
                        output / "dsp/mt8901-afe-sram.h", recorded, output)
    reusable.copy_provider_snapshot(output, recorded)
    reusable.copy_hwmon_snapshot(hwmon_repo, output, recorded)
    (output / "hwmon/Kbuild").write_text("obj-m += spbm.o\n")
    recorded["hwmon/Kbuild"] = sha256(output / "hwmon/Kbuild")

    vendor = f"usr/src/nvidia-{NVIDIA_VERSION}"
    subprocess.run(["bsdtar", "-xf", nvidia_archive, "-C", output,
                    "--strip-components", "2", vendor], check=True)
    tree = output / f"nvidia-{NVIDIA_VERSION}"
    p16 = REPO / "platform/nvidia/620"
    config = p16 / f"nvidia-{NVIDIA_VERSION}.conf"
    p16_patches = [p16 / name for name in
                   re.findall(r'^PATCH\[\d+\]="([^"]+)"$', config.read_text(), re.M)]
    if len(p16_patches) != 5:
        raise ValueError("Unexpected NVIDIA 620 P16 patch inventory")
    for patch in p16_patches + omarchy_patches:
        apply_patch(tree, patch)

    # DKMS reads the normal P16 series first, then this per-kernel override.
    supplemental = output / "dkms"
    supplemental.mkdir()
    for path in omarchy_patches:
        shutil.copyfile(path, supplemental / path.name)
    (supplemental / f"nvidia-{NVIDIA_VERSION}-{KERNEL_RELEASE}.conf").write_text(
        "".join(f'PATCH[{index}]="{path.name}"\n'
                for index, path in enumerate(omarchy_patches, start=len(p16_patches))))
    receipt = {
        "kernel_release": KERNEL_RELEASE,
        "nvidia_version": NVIDIA_VERSION,
        "vendor_archive_sha256": NVIDIA_HASH,
        "platform_sources": recorded,
        "nvidia_patches": {patch.name: sha256(patch) for patch in p16_patches + omarchy_patches},
    }
    (output / "driver-inputs.json").write_text(json.dumps(receipt, indent=2) + "\n")


def compile_modules(tree, output, jobs):
    if (tree / "include/config/kernel.release").read_text().strip() != KERNEL_RELEASE:
        raise ValueError(f"Expected kernel {KERNEL_RELEASE}")
    symbols = (tree / "Module.symvers").read_text()
    for suffix in ("retire", "stop_irq", "prepare_irq", "rebind", "allow_retention",
                   "suspend", "resume"):
        if f"\tmt8901_afe_sram_{suffix}\t" not in symbols:
            raise ValueError(f"Missing AFE export mt8901_afe_sram_{suffix}")
    inputs = json.loads((output / "driver-inputs.json").read_text())
    for relative, expected in inputs["platform_sources"].items():
        verify(output / relative, expected)
    jobs = f"-j{jobs}"
    for directory in PLATFORM:
        subprocess.run(["make", "-C", tree, jobs, f"M={output / directory}", "modules"],
                       check=True)
    vendor = output / f"nvidia-{NVIDIA_VERSION}"
    subprocess.run(["make", "-C", vendor, jobs, f"SYSSRC={tree}", f"SYSOUT={tree}",
                    f"KERNEL_UNAME={KERNEL_RELEASE}", "IGNORE_PREEMPT_RT_PRESENCE=1",
                    "NV_EXCLUDE_BUILD_MODULES=", "modules"], check=True)

    artifacts = [output / directory / f"{name}.ko" for directory, name in PLATFORM.items()]
    artifacts.extend(vendor / "kernel-open" / f"{name}.ko" for name in NVIDIA)
    for artifact in artifacts:
        vermagic = subprocess.check_output(["modinfo", "-F", "vermagic", artifact],
                                          text=True).split()
        if not vermagic or vermagic[0] != KERNEL_RELEASE:
            raise ValueError(f"Incorrect vermagic for {artifact}")
        subprocess.run([tree / "scripts/sign-file", "sha512",
                        tree / "certs/signing_key.pem", tree / "certs/signing_key.x509",
                        artifact], check=True)
    subprocess.run(["python3", REPO / "scripts/verify-module-btf.py",
                    "--vmlinux", tree / "vmlinux",
                    "--kernel-image", tree / "arch/arm64/boot/Image", *artifacts],
                   check=True)
    bundle = output / "bundle"
    bundle.mkdir()
    for path in artifacts:
        shutil.copyfile(path, bundle / path.name)
    inputs["built_modules"] = {path.name: sha256(path) for path in artifacts}
    (bundle / "provenance.json").write_text(json.dumps(inputs, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--nvidia-package", type=Path, required=True)
    parser.add_argument("--hwmon-source", type=Path, required=True)
    parser.add_argument("--kernel-tree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Build from previously staged sources")
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if not args.resume:
            stage(args.recipe.resolve(), args.nvidia_package.resolve(), args.hwmon_source.resolve(),
                  output)
        if not args.stage_only:
            compile_modules(args.kernel_tree.resolve(), output, args.jobs)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
