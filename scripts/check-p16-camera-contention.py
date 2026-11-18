#!/usr/bin/env python3
"""Check P16 RGB V4L2 exclusivity and recovery without saving camera pixels."""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path


def capture_args(device, frames):
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info",
            "-f", "v4l2", "-input_format", "mjpeg", "-video_size", "1280x720",
            "-framerate", "30", "-i", device, "-frames:v", str(frames),
            "-f", "null", "-"]


def frame_count(stderr):
    counts = re.findall(r"frame=\s*(\d+)", stderr)
    return int(counts[-1]) if counts else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    first = subprocess.Popen(capture_args(args.device, 120), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(1)
        if first.poll() is not None:
            raise RuntimeError("primary capture exited before contention probe")
        second = subprocess.run(capture_args(args.device, 10), capture_output=True,
                                text=True, timeout=12, check=False)
        _, first_stderr = first.communicate(timeout=12)
        third = subprocess.run(capture_args(args.device, 10), capture_output=True,
                               text=True, timeout=12, check=False)
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate()

    result = {
        "device": args.device,
        "primary": {"exit_code": first.returncode,
                    "frames": frame_count(first_stderr)},
        "concurrent": {"exit_code": second.returncode,
                       "busy": "Device or resource busy" in second.stderr,
                       "frames": frame_count(second.stderr)},
        "after_release": {"exit_code": third.returncode,
                          "frames": frame_count(third.stderr)},
        "retained_camera_pixels": False,
    }
    result["status"] = "pass" if (
        result["primary"] == {"exit_code": 0, "frames": 120}
        and result["concurrent"]["exit_code"] != 0
        and result["concurrent"]["busy"]
        and result["concurrent"]["frames"] == 0
        and result["after_release"] == {"exit_code": 0, "frames": 10}
    ) else "fail"
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
