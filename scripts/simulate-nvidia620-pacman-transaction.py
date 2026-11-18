#!/usr/bin/env python3
"""Check the 620 package transaction against a disposable pacman database.

Run under fakeroot. Only the copied database is modified; package payloads,
hooks, scriptlets, the live root and EFI files are not touched.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


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
REMOVE = ("linux-p16-platform-34-drivers", "linux-p16-platform-36-drivers",
          "linux-p16-platform-37-drivers", "linux-p16-platform-38-drivers",
          "nvidia-open-dkms", "n1x-nvidia-drm-fix")
EXPECTED = {"nvidia-utils": "620.70.06-1", "nvidia-open-dkms": "620.70.06-1",
            "n1x-nvidia-drm-fix-620": "620.70.06-1",
            "linux-p16-platform-38-drivers-nvidia620": "7.2.8-38"}
LIVE_PACKAGES = tuple(dict.fromkeys((*REMOVE, *EXPECTED)))


def run(command, *, timeout=45):
    return subprocess.run(command, capture_output=True, text=True,
                          check=False, timeout=timeout)


def versions(command):
    result = run(command)
    return {name: version for name, version in
            (line.split(" ", 1) for line in result.stdout.splitlines()
             if " " in line)}


def digest(path):
    hash_ = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            hash_.update(block)
    return hash_.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extract-payload", action="store_true",
                        help="also extract package files into the disposable root")
    args = parser.parse_args()
    if not os.environ.get("FAKEROOTKEY"):
        parser.error("run as: fakeroot -- python3 scripts/simulate-nvidia620-pacman-transaction.py ...")
    if args.output.exists():
        parser.error("choose a new output path")
    archives = {}
    for name, (relative, expected) in ARCHIVES.items():
        path = ROOT / relative
        actual = digest(path)
        if actual != expected:
            raise RuntimeError(f"archive hash mismatch: {relative}")
        archives[name] = {"path": relative, "sha256": actual}
    live_before = versions(["/usr/bin/pacman", "-Q", *LIVE_PACKAGES])
    with tempfile.TemporaryDirectory(prefix="p16-nvidia620-pacman-sim-") as folder:
        candidate = Path(folder) / "root"
        database = candidate / "var/lib/pacman"
        database.mkdir(parents=True)
        shutil.copytree("/var/lib/pacman/local", database / "local",
                        copy_function=shutil.copy2)
        shutil.copytree("/var/lib/pacman/sync", database / "sync",
                        copy_function=shutil.copy2)
        hookdir = candidate / "empty-hooks"
        hookdir.mkdir()
        (candidate / "usr/share/libalpm/hooks").mkdir(parents=True)
        (candidate / "etc/pacman.d/hooks").mkdir(parents=True)
        cache = candidate / "var/cache/pacman/pkg"
        cache.mkdir(parents=True)
        base = ["/usr/bin/pacman", "--root", str(candidate), "--dbpath",
                str(database), "--config", "/etc/pacman.conf",
                "--cachedir", str(cache), "--hookdir", str(hookdir),
                "--noscriptlet", "--noconfirm"]
        if not args.extract_payload:
            base.append("--dbonly")
        steps = []
        for label, operation in (("remove_615_drivers", ["-Rdd", *REMOVE]),
                                 ("install_620", ["-U", *(str(ROOT / path)
                                  for path, _ in ARCHIVES.values())])):
            result = run([*base, *operation])
            stderr_lines = result.stderr.splitlines()
            missing_old_files = [line for line in stderr_lines
                                 if line.startswith("warning: could not get file information for ")]
            unexpected_stderr = [line for line in stderr_lines
                                 if line not in missing_old_files]
            steps.append({"name": label, "exit_code": result.returncode,
                          "stdout_tail": result.stdout[-1500:].replace(str(folder), "$TMPROOT"),
                          "stderr_tail": result.stderr[-1000:].replace(str(folder), "$TMPROOT"),
                          "missing_old_payload_warning_count": len(missing_old_files),
                          "unexpected_stderr": unexpected_stderr[:20]})
            if result.returncode:
                break
        candidate_versions = versions(["/usr/bin/pacman", "--root", str(candidate),
                                       "--dbpath", str(database), "-Q", *LIVE_PACKAGES])
        payload_audit = None
        if args.extract_payload and len(steps) == 2 and all(
                step["exit_code"] == 0 for step in steps):
            payload_audit = {"packages": {}, "all_files_present": True}
            for name, (relative, _) in ARCHIVES.items():
                listed = run(["/usr/bin/bsdtar", "-tf", str(ROOT / relative)],
                             timeout=90)
                if listed.returncode:
                    raise RuntimeError(f"could not list archive {relative}")
                entries = listed.stdout.splitlines()
                files = [entry for entry in entries
                         if entry and not entry.startswith(".") and
                         not entry.endswith("/")]
                if not files:
                    raise RuntimeError(f"empty archive manifest: {relative}")
                missing = [entry for entry in files
                           if not os.path.lexists(candidate / entry)]
                payload_audit["packages"][name] = {
                    "archive_files": len(files), "present": len(files) - len(missing),
                    "missing": missing[:20], "missing_count": len(missing)}
                payload_audit["all_files_present"] &= not missing
            modules = sorted((candidate / "usr/lib/modules/7.2.8-38-rtx-spark-npu")
                             .rglob("*.ko"))
            payload_audit["extracted_module_count"] = len(modules)
            payload_audit["all_files_present"] &= len(modules) == 13
            qkk = run(["/usr/bin/pacman", "--root", str(candidate),
                       "--dbpath", str(database), "-Qkk", *EXPECTED], timeout=120)
            payload_audit["pacman_qkk"] = {
                "exit_code": qkk.returncode,
                "stdout_tail": qkk.stdout[-2000:].replace(str(folder), "$TMPROOT"),
                "stderr_tail": qkk.stderr[-1000:].replace(str(folder), "$TMPROOT")}
            payload_audit["all_files_present"] &= qkk.returncode == 0
    live_after = versions(["/usr/bin/pacman", "-Q", *LIVE_PACKAGES])
    passed = (len(steps) == 2 and all(step["exit_code"] == 0 for step in steps)
              and all(not step["unexpected_stderr"] for step in steps)
              and all(candidate_versions.get(name) == version
                      for name, version in EXPECTED.items())
              and all(name not in candidate_versions for name in REMOVE
                      if name != "nvidia-open-dkms")
              and live_before == live_after
              and live_after.get("nvidia-utils", "").startswith("615.")
              and (not args.extract_payload or
                   (payload_audit is not None and payload_audit["all_files_present"])))
    report = {"captured_at": datetime.now(timezone.utc).isoformat(),
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "operation": ("fakeroot pacman transaction with payload extraction into disposable root"
                            if args.extract_payload else
                            "fakeroot pacman --dbonly transaction on copied local/sync database"),
              "live_before": live_before, "live_after": live_after,
              "candidate_versions": candidate_versions, "archive_inputs": archives,
              "steps": steps, "pass": passed,
              "payload_audit": payload_audit,
              "limit": ("Disposable partial root only; actual Btrfs snapshot installation, ALPM hooks, module load, UKI and boot are untested."
                        if args.extract_payload else
                        "Database dependency and conflict resolution only; file conflicts, hooks, modules, UKI and boot are not tested.")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": passed, "candidate_versions": candidate_versions,
                      "live_root_unchanged": live_before == live_after}))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
