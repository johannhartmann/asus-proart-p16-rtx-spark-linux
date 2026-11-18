#!/usr/bin/env python3
"""Measure native P16 camera buffer sequences without FFmpeg or stored pixels."""

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
BUFFER = re.compile(
    r"cap dqbuf:\s*\d+ seq:\s*(\d+) bytesused:\s*(\d+) "
    r"ts:\s*([0-9.]+)")
WARNINGS = ("DMA-API:", "WARNING:", "BUG:", "KASAN:", "NVRM: Xid")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=3600)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 10 <= args.count <= 3600:
        parser.error("count must be 10–3600")
    if args.output.exists():
        parser.error("choose a new output path")
    command = ["/usr/bin/v4l2-ctl", "-d", CADENCE.CAMERA,
               "--set-fmt-video=width=1280,height=720,pixelformat=MJPG",
               "--set-parm=30", "--stream-mmap=4",
               "--stream-count=" + str(args.count), "--verbose"]
    since = int(time.time())
    started = time.monotonic()
    with CADENCE.exposure_control(True) as exposure:
        run = subprocess.run(command, capture_output=True, text=True,
                             timeout=args.count / 30 + 40, check=False)
    elapsed = time.monotonic() - started
    lines = (run.stdout + run.stderr).splitlines()
    buffers = [(int(seq), int(size), float(ts))
               for line in lines if (match := BUFFER.search(line))
               for seq, size, ts in [match.groups()]]
    sequence_gaps = [{"after_index": i, "previous": prev[0],
                      "next": current[0], "missing": current[0] - prev[0] - 1}
                     for i, (prev, current) in enumerate(zip(buffers, buffers[1:]))
                     if current[0] != prev[0] + 1]
    timestamp_gaps = [later[2] - earlier[2]
                      for earlier, later in zip(buffers, buffers[1:])]
    large_gaps = [{"after_index": i, "delta_seconds": round(gap, 6)}
                  for i, gap in enumerate(timestamp_gaps) if gap > 0.05]
    journal = subprocess.run(
        ["/usr/bin/journalctl", "-k", "-b", "--since", f"@{since}",
         "--no-pager", "-o", "short-iso"], capture_output=True, text=True,
        timeout=20, check=True).stdout.splitlines()
    warnings = [line for line in journal if any(token in line for token in WARNINGS)]
    errors = [line for line in lines if
              ("fail" in line.lower() or "error" in line.lower()) and
              "returned 0 (Success)" not in line]
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "device": CADENCE.CAMERA,
        "command": command,
        "exit_code": run.returncode,
        "requested_buffers": args.count,
        "observed_buffers": len(buffers),
        "elapsed_seconds": round(elapsed, 3),
        "first_sequence": buffers[0][0] if buffers else None,
        "last_sequence": buffers[-1][0] if buffers else None,
        "sequence_gap_events": sequence_gaps[:100],
        "sequence_gap_count": len(sequence_gaps),
        "large_timestamp_gap_events": large_gaps[:100],
        "large_timestamp_gap_count": len(large_gaps),
        "max_timestamp_gap_seconds": max(timestamp_gaps) if timestamp_gaps else None,
        "min_timestamp_gap_seconds": min(timestamp_gaps) if timestamp_gaps else None,
        "zero_byte_buffers": sum(size == 0 for _, size, _ in buffers),
        "control": exposure,
        "v4l2_error_lines": errors[:50],
        "new_kernel_warnings": warnings,
        "camera_pixels_retained": False,
    }
    result["pass"] = (run.returncode == 0 and len(buffers) == args.count and
                      not sequence_gaps and not large_gaps and
                      not result["zero_byte_buffers"] and
                      not errors and not warnings and
                      exposure["restored_dynamic_framerate"] ==
                      exposure["original_dynamic_framerate"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                      ("pass", "observed_buffers", "elapsed_seconds",
                       "sequence_gap_count", "large_timestamp_gap_count",
                       "zero_byte_buffers")}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
