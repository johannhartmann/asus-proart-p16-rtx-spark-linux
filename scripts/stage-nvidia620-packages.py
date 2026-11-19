#!/usr/bin/env python3
"""Install pinned NVIDIA 620 packages only into an existing @nvidia620 snapshot.

Default mode is read-only. --stage requires root through graphical Polkit,
refuses concurrent Pacman work, masks candidate ALPM hooks, disables package
scriptlets, and never writes EFI files, BootNext or the running root's packages.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RELEASE = "7.2.8-38-rtx-spark-npu"
TARGET = "@nvidia620"


def import_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SNAPSHOT = import_sibling("p16_nvidia620_snapshot", "stage-nvidia620-snapshot.py")
SIM = import_sibling("p16_nvidia620_sim", "simulate-nvidia620-pacman-transaction.py")


def run(command, *, timeout=120, check=True):
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if check and result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}: "
                           + result.stderr[-1000:])
    return result


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archives():
    result = {}
    for name, (relative, expected) in SIM.ARCHIVES.items():
        path = ROOT / relative
        result[name] = {"path": path, "sha256": sha256(path),
                        "expected": expected}
    return result


def plan():
    live = SNAPSHOT.plan()
    inputs = archives()
    all_hashes_match = all(item["sha256"] == item["expected"]
                           for item in inputs.values())
    return {"captured_at": datetime.now(timezone.utc).isoformat(),
            "live": live,
            "archives": {name: {"path": str(item["path"].relative_to(ROOT)),
                                "sha256": item["sha256"],
                                "hash_matches": item["sha256"] == item["expected"]}
                         for name, item in inputs.items()},
            "target_subvolume": TARGET,
            "ready_for_root_stage": live["ready_to_stage"] and all_hashes_match,
            "read_only": True}


def pacman(candidate, *args, check=True):
    return run(["/usr/bin/pacman", "--sysroot", str(candidate), "--config",
                "/etc/pacman.conf", *args], check=check)


def versions(candidate, names):
    result = pacman(candidate, "-Q", *names, check=False)
    return dict(line.split(" ", 1) for line in result.stdout.splitlines()
                if " " in line)


def assert_no_package_hook_paths(candidate, inputs):
    # Bind masking is safe only if none of the changed packages owns hooks.
    names = tuple(dict.fromkeys((*SIM.REMOVE, "nvidia-utils")))
    listed = pacman(candidate, "-Ql", *names, check=False)
    if listed.returncode:
        raise RuntimeError("could not inspect candidate package hook ownership")
    hook_roots = ("usr/share/libalpm/hooks/", "etc/pacman.d/hooks/")
    owned = [line for line in listed.stdout.splitlines()
             if " " in line and
             line.split(" ", 1)[1].lstrip("/").startswith(hook_roots)]
    if owned:
        raise RuntimeError("changed installed package owns ALPM hooks")
    for item in inputs.values():
        manifest = run(["/usr/bin/bsdtar", "-tf", str(item["path"])],
                       timeout=90).stdout.splitlines()
        if any(path.lstrip("./").startswith("boot/") for path in manifest):
            raise RuntimeError("candidate package contains EFI/boot files")
        if any(path.lstrip("./").startswith(hook_roots) for path in manifest):
            raise RuntimeError("candidate package contains ALPM hooks")
    config = (candidate / "etc/pacman.conf").read_text()
    if re.search(r"^\s*HookDir\s*=", config, re.MULTILINE):
        raise RuntimeError("candidate Pacman config has a custom HookDir")


def snapshot_id(candidate):
    return SNAPSHOT.snapshot_id(candidate)


def run_preflight(folder):
    output = folder / "preflight.json"
    run(["/usr/bin/python3", str(HERE / "check-nvidia620-staging-inputs.py"),
         "--output", str(output)], timeout=180)
    result = json.loads(output.read_text())
    if not result["pass"]:
        raise RuntimeError("signed archive/module/EFI preflight failed")
    return {"pass": True, "driver_module_count": result["driver_module_count"],
            "efi_free_bytes": result["efi_free_bytes"]}


def stage(state, output, resume_from=None):
    if os.geteuid() != 0:
        raise RuntimeError("--stage requires root through graphical Polkit")
    if not state["ready_for_root_stage"]:
        raise RuntimeError("live/auth/archive preflight is not ready")
    if output.exists():
        raise RuntimeError("choose a new output receipt")
    prior = None
    if resume_from is not None:
        raw = resume_from.read_bytes()
        prior = json.loads(raw)
        expected_steps = ("remove_615_drivers", "install_620", "verify_620_files")
        if prior.get("pass") is not False or \
                prior.get("failure") != "candidate does not have 13 kernel38 modules" or \
                prior.get("candidate_subvolume") != TARGET or \
                [(item.get("name"), item.get("exit_code"))
                 for item in prior.get("steps", [])] != [(name, 0) for name in expected_steps] or \
                prior.get("live_packages_before") != state["live"]["packages"] or \
                prior.get("live_packages_after") != state["live"]["packages"] or \
                prior.get("boot_before") != state["live"]["boot"] or \
                prior.get("boot_after") != state["live"]["boot"] or \
                prior.get("efi_sha256_before") != prior.get("efi_sha256_after") or \
                prior.get("reboot_executed") is not False:
            raise RuntimeError("prior receipt is not the exact successful transaction with module-count check failure")
        prior_sha256 = hashlib.sha256(raw).hexdigest()
    before_boot = state["live"]["boot"]
    before_packages = state["live"]["packages"]
    live_changed_names = tuple(dict.fromkeys((*SIM.REMOVE, "nvidia-utils")))
    live_changed = dict(line.split(" ", 1) for line in
                        run(["/usr/bin/pacman", "-Q", *live_changed_names])
                        .stdout.splitlines())
    before_efi = SNAPSHOT.boot_hashes()
    if not before_efi:
        raise RuntimeError("no readable EFI images")
    if prior and before_efi != prior["efi_sha256_after"]:
        raise RuntimeError("EFI rollback files changed after prior transaction")
    inputs = archives()
    if any(item["sha256"] != item["expected"] for item in inputs.values()):
        raise RuntimeError("620 package archive changed after plan")
    folder = Path(tempfile.mkdtemp(prefix="p16-nvidia620-packages-", dir="/run"))
    candidate = folder / "candidate"
    empty_hooks = folder / "empty-hooks"
    candidate.mkdir(mode=0o700)
    empty_hooks.mkdir(mode=0o700)
    try:
        preflight = run_preflight(folder)
    except Exception:
        (folder / "preflight.json").unlink(missing_ok=True)
        candidate.rmdir()
        empty_hooks.rmdir()
        folder.rmdir()
        raise
    lock = Path("/var/lib/pacman/db.lck")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except Exception:
        (folder / "preflight.json").unlink()
        candidate.rmdir()
        empty_hooks.rmdir()
        folder.rmdir()
        raise
    lock_inode = os.fstat(lock_fd).st_ino
    os.write(lock_fd, (str(os.getpid()) + "\n").encode())
    mounted = []
    steps = list(prior["steps"]) if prior else []
    candidate_id = None
    failure = None
    try:
        if SNAPSHOT.pending_pacman_auth() or SNAPSHOT.package_versions() != before_packages:
            raise RuntimeError("live package state changed after plan")
        run(["/usr/bin/mount", "-t", "btrfs", "-o", f"subvol={TARGET}",
             state["live"]["mount"]["device"], str(candidate)])
        mounted.append(candidate)
        candidate_id = snapshot_id(candidate)
        if candidate_id == 256 or (candidate / "var/lib/pacman/db.lck").exists():
            raise RuntimeError("candidate subvolume ID or Pacman lock is invalid")
        if prior and candidate_id != prior["candidate_id"]:
            raise RuntimeError("candidate subvolume differs from prior transaction")
        if run(["/usr/bin/findmnt", "-M", str(candidate / "boot")],
               check=False).returncode == 0:
            raise RuntimeError("candidate /boot must remain unmounted")
        initial = versions(candidate, live_changed_names)
        if prior:
            expected_installed = {name: SIM.EXPECTED[name]
                                  for name in live_changed_names if name in SIM.EXPECTED}
            if initial != expected_installed or versions(candidate, SIM.EXPECTED) != SIM.EXPECTED:
                raise RuntimeError("candidate no longer has the exact 620 transaction result")
            steps.append({"name": "resume_existing_620", "exit_code": 0,
                          "detail": "reverify existing candidate; no package transaction"})
        else:
            if initial != live_changed:
                raise RuntimeError("candidate 615 package state differs from live root")
            if any(name in initial for name in ("n1x-nvidia-drm-fix-620",
                                                 "linux-p16-platform-38-drivers-nvidia620")):
                raise RuntimeError("candidate already contains NVIDIA 620 packages")
            assert_no_package_hook_paths(candidate, inputs)
            for relative in ("usr/share/libalpm/hooks", "etc/pacman.d/hooks"):
                target = candidate / relative
                if not target.is_dir():
                    raise RuntimeError(f"candidate hook directory missing: {relative}")
                run(["/usr/bin/mount", "--bind", str(empty_hooks), str(target)])
                mounted.append(target)
            base = ("--noscriptlet", "--noconfirm")
            for label, args in (
                    ("remove_615_drivers", (*base, "-Rdd", *SIM.REMOVE)),
                    ("install_620", (*base, "-U", *(str(item["path"])
                                             for item in inputs.values())))):
                result = pacman(candidate, *args, check=False)
                steps.append({"name": label, "exit_code": result.returncode,
                              "stdout_tail": result.stdout[-1800:].replace(str(folder), "$STAGE").replace(str(ROOT), "$REPO"),
                              "stderr_tail": result.stderr[-1200:].replace(str(folder), "$STAGE").replace(str(ROOT), "$REPO")})
                if result.returncode:
                    raise RuntimeError(f"candidate Pacman {label} failed")
        qkk = pacman(candidate, "-Qkk", *SIM.EXPECTED, check=False)
        steps.append({"name": "verify_620_files", "exit_code": qkk.returncode,
                      "stdout_tail": qkk.stdout[-1800:].replace(str(folder), "$STAGE").replace(str(ROOT), "$REPO"),
                      "stderr_tail": qkk.stderr[-1200:].replace(str(folder), "$STAGE").replace(str(ROOT), "$REPO")})
        if qkk.returncode or "altered files" not in qkk.stdout or re.search(
                r"[1-9]\d* altered files", qkk.stdout):
            raise RuntimeError("candidate package file verification failed")
        module_dir = candidate / "usr/lib/modules" / RELEASE / "updates/dkms"
        package_manifest = run(["/usr/bin/bsdtar", "-tf", str(inputs[
            "linux-p16-platform-38-drivers-nvidia620"]["path"])], timeout=90)
        package_modules = {Path(path).name for path in package_manifest.stdout.splitlines()
                           if path.startswith(f"usr/lib/modules/{RELEASE}/updates/dkms/")
                           and path.endswith(".ko")}
        installed_modules = {path.name for path in module_dir.glob("*.ko")}
        extra_modules = installed_modules - package_modules
        if len(package_modules) != 13 or not package_modules <= installed_modules or \
                extra_modules not in (set(), {"cpuid.ko"}):
            raise RuntimeError("candidate packaged kernel38 module set differs from archive")
        if extra_modules and sha256(module_dir / "cpuid.ko") != sha256(
                Path("/usr/lib/modules") / RELEASE / "updates/dkms/cpuid.ko"):
            raise RuntimeError("pre-existing unowned cpuid module changed in candidate")
        steps.append({"name": "verify_kernel38_modules", "exit_code": 0,
                      "packaged_modules": sorted(package_modules),
                      "preexisting_extra_modules": sorted(extra_modules)})
        run(["/usr/bin/depmod", "-b", str(candidate), RELEASE], timeout=90)
        if versions(candidate, SIM.EXPECTED) != SIM.EXPECTED:
            raise RuntimeError("candidate 620 package versions do not match")
    except Exception as error:
        failure = str(error)
    finally:
        cleanup_error = None
        for mountpoint in reversed(mounted):
            try:
                run(["/usr/bin/umount", str(mountpoint)])
            except Exception as error:
                cleanup_error = str(error)
                break
        if cleanup_error is None:
            candidate.rmdir()
            empty_hooks.rmdir()
            (folder / "preflight.json").unlink()
            folder.rmdir()
        else:
            failure = (failure + "; " if failure else "") + \
                "private mount cleanup failed: " + cleanup_error
        os.close(lock_fd)
        if lock.stat().st_ino != lock_inode:
            raise RuntimeError("live Pacman lock was replaced; refusing to remove it")
        lock.unlink()
    after = SNAPSHOT.plan()
    after_changed = dict(line.split(" ", 1) for line in
                         run(["/usr/bin/pacman", "-Q", *live_changed_names])
                         .stdout.splitlines())
    after_efi = SNAPSHOT.boot_hashes()
    pass_ = (failure is None and candidate_id not in (None, 256) and
             before_boot == after["boot"] and
             before_packages == after["packages"] and
             live_changed == after_changed and
             before_efi == after_efi and
             state["live"]["boot_id"] == after["boot_id"])
    receipt = {"captured_at": datetime.now(timezone.utc).isoformat(),
               "pass": pass_, "failure": failure,
               "candidate_subvolume": TARGET, "candidate_id": candidate_id,
               "signed_archive_preflight": preflight,
               "resumed_from": str(resume_from) if prior else None,
               "resumed_from_sha256": prior_sha256 if prior else None,
               "steps": steps,
               "live_packages_before": before_packages,
               "live_packages_after": after["packages"],
               "live_changed_packages_before": live_changed,
               "live_changed_packages_after": after_changed,
               "boot_before": before_boot, "boot_after": after["boot"],
               "efi_sha256_before": before_efi,
               "efi_sha256_after": after_efi,
               "reboot_executed": False, "boot_entry_created": False,
               "next_gate": "build and verify a distinct kernel38/620 UKI from this candidate"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    owner = os.environ.get("PKEXEC_UID", "")
    if owner.isdecimal() and int(owner) > 0:
        os.chown(output, int(owner), -1)
    print(json.dumps({"pass": pass_, "candidate_id": candidate_id,
                      "failure": failure, "live_unchanged": before_packages == after["packages"]}))
    return 0 if pass_ else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume-from", type=Path,
                        help="failed receipt after completed 620 transaction; reverify without reinstalling")
    args = parser.parse_args()
    if args.stage and args.output is None:
        parser.error("--stage requires --output")
    if args.resume_from and not args.stage:
        parser.error("--resume-from requires --stage")
    state = plan()
    if not args.stage:
        print(json.dumps(state, indent=2))
        return 0
    return stage(state, args.output, args.resume_from)


if __name__ == "__main__":
    sys.exit(main())
