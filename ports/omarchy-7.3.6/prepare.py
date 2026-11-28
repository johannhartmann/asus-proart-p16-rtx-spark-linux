#!/usr/bin/env python3
"""Reconstruct the Omarchy ARM64 kernel and apply the P16 overlay offline."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

PORT = Path(__file__).resolve().parent
REPO = PORT.parents[1]
OMARCHY_REVISION = "d9fff5fcc96e4539c009f56884a1d10631e1557a"
RECIPE_HASH = "8cacf044b0f3616da4b307a550fbfc7d74cf21cbf6dc0a4463e0b12df6eec9d7"
CONFIG_HASH = "de9d0bf1fc17a49e63c3737964ec5571501497ba8fd72214012e3f17555d39ea"
KERNEL_VERSION = "7.3.6"
KERNEL_RELEASE = "7.3.6-10-omarchy-p16"
HEADERS_HASH = "5e3670786b9ff41c39cd12703d6c11e748e9aeadc5bfe45d9cd9f7692930ce15"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(path, expected):
    if sha256(path) != expected:
        raise ValueError(f"Unexpected SHA-256 for {path}")


def recipe_patches(recipe, linux_source):
    pkgbuild = recipe / "PKGBUILD"
    verify(pkgbuild, RECIPE_HASH)
    entries = subprocess.check_output(
        ["bash", "--noprofile", "--norc", "-c", """
source "$1"
test "${#source[@]}" = "${#sha256sums[@]}" || exit 1
for ((i=0;i<${#source[@]};i++)); do
    printf '%s\t%s\n' "${source[i]}" "${sha256sums[i]}"
done
""", "read-pkgbuild", str(pkgbuild)], text=True).splitlines()
    linux = []
    nvidia = []
    for entry in entries:
        url, expected = entry.split("\t")
        name = url.rsplit("/", 1)[-1]
        if name == f"linux-{KERNEL_VERSION}.tar.xz" and linux_source is not None:
            verify(linux_source, expected)
        if name.endswith((".patch", ".patch.zst")):
            path = recipe / name
            verify(path, expected)
            (nvidia if name.startswith("nvidia-") else linux).append(path)
    if len(linux) != 616 or len(nvidia) != 7:
        raise ValueError("Unexpected patch inventory")
    return linux, nvidia


def apply_patch(tree, path, *, git=False):
    with tempfile.TemporaryFile() as stream:
        if path.suffix == ".zst":
            subprocess.run(["zstd", "-dc", path], stdout=stream, check=True)
        else:
            stream.write(path.read_bytes())
        stream.seek(0)
        print(f"Applying {path.name}", flush=True)
        if git:
            # Treat this extracted kernel as a standalone tree even if the
            # build directory lives inside the P16 repository.
            subprocess.run(["git", "apply", "--whitespace=error", "-"], cwd=tree,
                           stdin=stream, check=True,
                           env=dict(os.environ, GIT_CEILING_DIRECTORIES=str(tree.parent)))
        else:
            subprocess.run(["patch", "--batch", "--forward", "--fuzz=0",
                            "--no-backup-if-mismatch", "-p1"], cwd=tree,
                           stdin=stream, check=True)


def stock_config(headers):
    verify(headers, HEADERS_HASH)
    config = subprocess.check_output(["bsdtar", "-xOf", headers,
                                      "usr/lib/modules/7.3.6-10-omarchy/build/.config"])
    if hashlib.sha256(config).hexdigest() != CONFIG_HASH:
        raise ValueError("Incorrect ARM64 kernel configuration")
    return config


def prepare(recipe, source, headers, output, verify_only):
    patches, _ = recipe_patches(recipe, source)
    config = stock_config(headers)
    series = [REPO / line for line in (PORT / "series").read_text().splitlines()]
    fingerprint = {
        "omarchy_revision": OMARCHY_REVISION,
        "kernel_release": KERNEL_RELEASE,
        "kernel_archive_sha256": sha256(source),
        "headers_archive_sha256": HEADERS_HASH,
        "omarchy_kernel_patches": len(patches),
        "p16_patches": {str(path.relative_to(REPO)): sha256(path) for path in series},
        "config_fragment_sha256": sha256(PORT / "config.fragment"),
    }
    if verify_only:
        print(json.dumps(fingerprint, indent=2))
        return

    output.mkdir(parents=True)
    subprocess.run(["bsdtar", "-xf", source, "-C", output], check=True)
    tree = output / f"linux-{KERNEL_VERSION}"
    for path in patches + series:
        apply_patch(tree, path, git=path.name == "asus-arm64-wmi.patch")
    (tree / ".config").write_bytes(config)
    (tree / "localversion.10-pkgrel").write_text("-10-omarchy-p16\n")
    subprocess.run(["bash", "scripts/kconfig/merge_config.sh", "-m",
                    ".config", PORT / "config.fragment"], cwd=tree, check=True)
    subprocess.run(["make", "olddefconfig"], cwd=tree, check=True)
    release = subprocess.check_output(["make", "-s", "kernelrelease"], cwd=tree,
                                      text=True).strip()
    if release != KERNEL_RELEASE:
        raise ValueError(f"Unexpected kernel release {release}")
    (tree / "version").write_text(release + "\n")
    (output / "kernel-inputs.json").write_text(json.dumps(fingerprint, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--linux-source", type=Path, required=True)
    parser.add_argument("--stock-headers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        prepare(args.recipe.resolve(), args.linux_source.resolve(), args.stock_headers.resolve(),
                args.output.resolve(), args.verify_only)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
