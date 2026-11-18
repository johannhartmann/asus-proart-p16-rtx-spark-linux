#!/usr/bin/env python3
"""Check the P16 RGB camera's UVC privacy control and live output."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    controls = subprocess.run(
        ["v4l2-ctl", "-d", "/dev/video0", "--list-ctrls"],
        capture_output=True, text=True, check=True, timeout=5)
    before = subprocess.run(
        ["v4l2-ctl", "-d", "/dev/video0", "-C", "privacy"],
        capture_output=True, text=True, check=True, timeout=5)
    brightness = subprocess.run(
        ["v4l2-ctl", "-d", "/dev/video0", "-C", "brightness"],
        capture_output=True, text=True, check=True, timeout=5)
    brightness_value = int(brightness.stdout.strip().split(":", 1)[1])
    writable_control = subprocess.run(
        ["v4l2-ctl", "-d", "/dev/video0",
         f"--set-ctrl=brightness={brightness_value}"],
        capture_output=True, text=True, check=False, timeout=5)
    set_attempt = subprocess.run(
        ["v4l2-ctl", "-d", "/dev/video0", "--set-ctrl=privacy=1"],
        capture_output=True, text=True, check=False, timeout=5)
    after = subprocess.run(
        ["v4l2-ctl", "-d", "/dev/video0", "-C", "privacy"],
        capture_output=True, text=True, check=True, timeout=5)
    capture = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "info", "-f", "v4l2",
         "-input_format", "mjpeg", "-video_size", "1280x720", "-framerate", "30",
         "-i", "/dev/video0", "-frames:v", "30", "-vf",
         "signalstats,metadata=print", "-f", "null", "-"],
        capture_output=True, text=True, check=False, timeout=15)
    yavg = [float(value) for value in re.findall(
        r"lavfi\.signalstats\.YAVG=([0-9.]+)", capture.stderr)]
    ymin = [int(value) for value in re.findall(
        r"lavfi\.signalstats\.YMIN=([0-9]+)", capture.stderr)]
    ymax = [int(value) for value in re.findall(
        r"lavfi\.signalstats\.YMAX=([0-9]+)", capture.stderr)]
    privacy_read_only = bool(re.search(r"\bprivacy\b[^\n]*flags=read-only", controls.stdout))
    passed = (privacy_read_only and before.stdout.strip() == "privacy: 0" and
              writable_control.returncode == 0 and
              set_attempt.returncode != 0 and after.stdout.strip() == "privacy: 0" and
              capture.returncode == 0 and len(yavg) == 30 and
              len(ymin) == 30 and len(ymax) == 30)
    result = {
        "status": "pass" if passed else "fail",
        "device": "/dev/video0", "format": "MJPEG 1280x720 30 fps",
        "physical_shutter_present": False,
        "physical_shutter_source": "user report",
        "v4l2_privacy_read_only": privacy_read_only,
        "writable_brightness_control": brightness.stdout.strip(),
        "set_brightness_same_value_exit_code": writable_control.returncode,
        "v4l2_privacy_before": before.stdout.strip(),
        "v4l2_set_privacy_exit_code": set_attempt.returncode,
        "v4l2_set_privacy_error": set_attempt.stderr.strip(),
        "v4l2_privacy_after": after.stdout.strip(),
        "frames": len(yavg), "mean_luma_min": min(yavg) if yavg else None,
        "mean_luma_max": max(yavg) if yavg else None,
        "mean_luma_average": sum(yavg) / len(yavg) if yavg else None,
        "pixel_min": min(ymin) if ymin else None,
        "pixel_max": max(ymax) if ymax else None,
        "ffmpeg_exit_code": capture.returncode,
        "retained_camera_pixels": False,
        "note": "UVC privacy is read-only at 0; this does not test an undocumented electronic shutter or camera LED."
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
