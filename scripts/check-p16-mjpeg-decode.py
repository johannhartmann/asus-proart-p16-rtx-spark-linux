#!/usr/bin/env python3
"""Decode a sustained live P16 MJPEG stream without a recorder or saved pixels."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time


SPEC = importlib.util.spec_from_file_location(
    "p16_cadence", Path(__file__).with_name("check-p16-camera-cadence.py"))
CADENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CADENCE)
WARNINGS = ("DMA-API:", "WARNING:", "BUG:", "KASAN:", "NVRM: Xid")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=3600)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 10 <= args.frames <= 3600:
        parser.error("frames must be 10–3600")
    if args.output.exists():
        parser.error("choose a new output path")
    command = ["/usr/bin/ffmpeg", "-hide_banner", "-nostdin", "-stats",
               "-f", "v4l2", "-input_format", "mjpeg", "-video_size",
               "1280x720", "-framerate", "30", "-i", CADENCE.CAMERA,
               "-frames:v", str(args.frames), "-fps_mode", "passthrough",
               "-f", "null", "-"]
    since = int(time.time())
    started = time.monotonic()
    with CADENCE.exposure_control(True) as exposure:
        run = subprocess.run(command, capture_output=True, text=True,
                             timeout=args.frames / 30 + 45, check=False)
    elapsed = time.monotonic() - started
    lines = (run.stdout + run.stderr).replace("\r", "\n").splitlines()
    counts = re.findall(r"frame=\s*(\d+)", run.stderr)
    errors = [line.strip() for line in lines if
              re.search(r"corrupt|error|invalid|drop|non.monoton", line, re.I)]
    timestamp_errors = [line for line in errors if
                        "non monotonically increasing dts" in line]
    payload_errors = [line for line in errors if line not in timestamp_errors]
    journal = subprocess.run(
        ["/usr/bin/journalctl", "-k", "-b", "--since", f"@{since}",
         "--no-pager", "-o", "short-iso"], capture_output=True, text=True,
        timeout=20, check=True).stdout.splitlines()
    warnings = [line for line in journal if any(token in line for token in WARNINGS)]
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "device": CADENCE.CAMERA,
        "command": command,
        "exit_code": run.returncode,
        "requested_decoded_frames": args.frames,
        "reported_output_frames": int(counts[-1]) if counts else None,
        "elapsed_seconds": round(elapsed, 3),
        "ffmpeg_error_lines": errors[:50],
        "payload_error_lines": payload_errors[:50],
        "timestamp_mux_error_count": len(timestamp_errors),
        "new_kernel_warnings": warnings,
        "control": exposure,
        "camera_pixels_retained": False,
    }
    result["decode_pass"] = (run.returncode == 0 and
                             result["reported_output_frames"] == args.frames and
                             not payload_errors and not warnings and
                             exposure["restored_dynamic_framerate"] ==
                             exposure["original_dynamic_framerate"])
    result["timestamp_mux_pass"] = not timestamp_errors
    result["pass"] = result["decode_pass"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                      ("pass", "reported_output_frames", "elapsed_seconds",
                       "exit_code", "timestamp_mux_error_count",
                       "payload_error_lines")}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
