#!/usr/bin/env python3
"""Boot a candidate ARM64 Image under KVM and check release and Lockdep.

This is a direct-kernel smoke test. It neither tests the EFI UKI nor loads
platform modules, and it does not alter the host boot configuration.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time


INIT = r'''
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

int main(void)
{
    mkdir("/dev", 0755);
    mount("devtmpfs", "/dev", "devtmpfs", 0, NULL);
    int fd = open("/dev/console", O_RDWR);
    if (fd >= 0) {
        dup2(fd, 0);
        dup2(fd, 1);
        dup2(fd, 2);
    }
    mkdir("/proc", 0755);
    mount("proc", "/proc", "proc", 0, NULL);
    struct utsname identity;
    uname(&identity);
    FILE *file = fopen("/proc/lockdep_stats", "r");
    char line[256];
    int debug_locks = -1;
    if (file) {
        while (fgets(line, sizeof(line), file)) {
            if (strstr(line, "debug_locks:"))
                sscanf(line, " debug_locks: %d", &debug_locks);
        }
        fclose(file);
    }
    printf("KERNEL_SMOKE release=%s debug_locks=%d\n",
           identity.release, debug_locks);
    fflush(stdout);
    sync();
    reboot(RB_POWER_OFF);
    for (;;)
        pause();
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    image = args.image.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "init.c").write_text(INIT)
    subprocess.run(["cc", "-static", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-o", str(output / "init"), str(output / "init.c")], check=True)
    with (output / "init.cpio").open("wb") as archive:
        subprocess.run(["cpio", "-o", "-H", "newc"], input=b"init\n",
                       cwd=output, stdout=archive, stderr=subprocess.PIPE,
                       check=True)
    command = ["qemu-system-aarch64", "-machine", "virt,accel=kvm,gic-version=3",
               "-cpu", "host", "-smp", "2", "-m", "2048", "-display", "none",
               "-serial", "stdio", "-monitor", "none", "-no-reboot",
               "-kernel", str(image), "-initrd", str(output / "init.cpio"),
               "-append", "console=ttyAMA0 loglevel=4 panic=0"]
    started = time.monotonic()
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=90, check=False)
        log = done.stdout + done.stderr
        code = done.returncode
    except subprocess.TimeoutExpired as error:
        log = "".join(chunk.decode(errors="replace") if isinstance(chunk, bytes)
                      else chunk or "" for chunk in (error.stdout, error.stderr))
        code = 124
    (output / "uart.log").write_text(log)
    marker = re.search(r"KERNEL_SMOKE release=(\S+) debug_locks=(-?\d+)", log)
    warnings = [line for line in log.splitlines()
                if any(token in line for token in ("WARNING:", "BUG:", "KASAN:"))]
    result = {
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "expected_release": args.expected_release,
        "observed_release": marker.group(1) if marker else None,
        "debug_locks": int(marker.group(2)) if marker else None,
        "qemu_exit_code": code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "warning_lines": warnings,
        "direct_kernel_boot_only": True,
        "host_modules_loaded": False,
        "host_pm_requested": False,
    }
    result["pass"] = (code == 0 and marker is not None and
                      result["observed_release"] == args.expected_release and
                      result["debug_locks"] == 1 and not warnings)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"],
                      "release": result["observed_release"],
                      "debug_locks": result["debug_locks"],
                      "warnings": len(warnings)}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
