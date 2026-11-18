#!/usr/bin/env python3
"""Run the P16 UVC DMA check with temporary kernel trace via one Polkit call.

Invoke as: pkexec --disable-internal-agent /usr/bin/python3 ABSOLUTE_SCRIPT
  --output-dir USER_WRITABLE_NEW_DIRECTORY --include-streamcam
The camera checker runs as the original desktop user; only the trace write
uses root. The prior trace mask is restored even when capture fails.
"""

import argparse
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys


TRACE = Path("/sys/module/uvcvideo/parameters/trace")
TRACE_BIT = 1024
CHECKER = Path(__file__).resolve().with_name("check-p16-uvc-dma.py")


def trace_value():
    return int(TRACE.read_text().strip())


def write_trace(value):
    TRACE.write_text(f"{value}\n")
    if trace_value() != value:
        raise RuntimeError("UVC trace readback did not match requested value")


def invoke_checker(user, output_dir, streamcam):
    command = ["/usr/bin/runuser", "-u", user.pw_name, "--",
               "/usr/bin/python3", str(CHECKER), "--output-dir",
               str(output_dir)]
    if streamcam:
        command.append("--include-streamcam")
    process = subprocess.Popen(command, start_new_session=True)
    try:
        return process.wait(timeout=120)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        raise RuntimeError("UVC checker exceeded 120 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--include-streamcam", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("root required through graphical Polkit")
    uid_text = os.environ.get("PKEXEC_UID", "")
    if not uid_text.isdecimal() or int(uid_text) == 0:
        parser.error("PKEXEC_UID must identify the unprivileged desktop user")
    user = pwd.getpwuid(int(uid_text))
    output_dir = args.output_dir.resolve(strict=False)
    if output_dir.exists():
        parser.error("choose a new output directory")
    if not CHECKER.is_file() or not TRACE.is_file():
        parser.error("checker or UVC trace control is unavailable")
    if args.include_streamcam and not Path(
            "/dev/v4l/by-path/platform-NVDA8000:00-usb-0:1.1:1.0-video-index0").exists():
        parser.error("external StreamCam is not connected")
    original = trace_value()
    try:
        write_trace(original | TRACE_BIT)
        exit_code = invoke_checker(user, output_dir, args.include_streamcam)
    finally:
        # Preserve other bits if another trace setting changed during capture.
        current = trace_value()
        write_trace((current & ~TRACE_BIT) | (original & TRACE_BIT))
    print(f"UVC trace restored to {trace_value()}; checker exit code {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
