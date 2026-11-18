#!/usr/bin/env python3
"""Capture the P16 cameras and check UVC URB sizes against the XHCI DMA limit.

Enable uvcvideo trace bit 1024 before running and restore the original setting
afterwards. The caller performs those privileged writes through desktop polkit.
No image or video data is kept.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time


RGB = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.0-video-index0"
IR = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.2-video-index0"
CASES = (
    ("rgb-720p", RGB, "mjpeg", "1280x720", 30, 60),
    ("rgb-1080p", RGB, "mjpeg", "1920x1080", 30, 60),
    ("ir-360p", IR, "gray", "360x360", 15, 30),
)
URB = re.compile(r"Allocated \d+ URB buffers of (\d+)x(\d+) bytes each")
WARNINGS = ("DMA-API:", "WARNING:", "BUG:", "KASAN:", "NVRM: Xid")


def capture(name, device, fmt, size, fps, frames, directory):
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-f", "v4l2",
               "-input_format", fmt, "-framerate", str(fps),
               "-video_size", size, "-i", device, "-frames:v", str(frames),
               "-f", "null", "-"]
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=max(30, frames // fps + 20), check=False)
        log = done.stdout + done.stderr
        code = done.returncode
    except subprocess.TimeoutExpired as error:
        chunks = (error.stdout, error.stderr)
        log = "".join(chunk.decode(errors="replace") if isinstance(chunk, bytes)
                      else chunk or "" for chunk in chunks)
        code = 124
    (directory / f"{name}.log").write_text(log)
    counts = re.findall(r"frame=\s*(\d+)", log)
    return {"command": command, "exit_code": code,
            "frames": int(counts[-1]) if counts else 0,
            "expected_frames": frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-segment", type=int, default=65536)
    args = parser.parse_args()
    trace = int(Path("/sys/module/uvcvideo/parameters/trace").read_text().strip())
    if not trace & 1024:
        parser.error("enable uvcvideo trace bit 1024 before this check")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    since = int(time.time())
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": subprocess.check_output(["uname", "-r"], text=True).strip(),
        "trace_during": trace,
        "max_dma_segment_bytes": args.max_segment,
        "camera_pixels_retained": False,
        "cases": {},
    }
    for case in CASES:
        result["cases"][case[0]] = capture(*case, args.output_dir)
    journal = subprocess.run(
        ["journalctl", "-k", "-b", "--since", f"@{since}", "--no-pager",
         "-o", "short-iso"], capture_output=True, text=True, check=True,
        timeout=15).stdout.splitlines()
    uvc = [line for line in journal if "uvcvideo" in line and
           ("Limiting URB" in line or "Allocated " in line)]
    warnings = [line for line in journal if any(token in line for token in WARNINGS)]
    allocations = []
    for line in uvc:
        match = URB.search(line)
        if match:
            packets, packet_bytes = map(int, match.groups())
            requested = packets * packet_bytes
            rounded = (requested + 4095) // 4096 * 4096
            allocations.append({"packets": packets, "packet_bytes": packet_bytes,
                                "requested_bytes": requested,
                                "page_rounded_bytes": rounded,
                                "within_dma_limit": rounded <= args.max_segment})
    result["uvc_trace_lines"] = uvc
    result["allocations"] = allocations
    result["new_kernel_warnings"] = warnings
    expected_rgb_packets = args.max_segment // 4096 * 4096 // 2940
    rgb_capped = sum(f"Limiting URB to {expected_rgb_packets} packets" in line
                     for line in uvc) >= 2
    result["pass"] = (all(item["exit_code"] == 0 and
                          item["frames"] == item["expected_frames"]
                          for item in result["cases"].values()) and
                      len(allocations) >= 3 and
                      all(item["within_dma_limit"] for item in allocations) and
                      rgb_capped and not warnings)
    (args.output_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "cases": result["cases"],
                      "allocations": allocations, "warnings": len(warnings)}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
