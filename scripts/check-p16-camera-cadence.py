#!/usr/bin/env python3
"""Measure the P16 RGB camera's MJPEG/V4L2 cadence without a video encoder."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("p16_nvof_soak", HERE / "check-p16-nvof-soak.py")
SOAK = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SOAK)
CAMERA = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.0-video-index0"


def dynamic_framerate():
    output = subprocess.check_output(
        ["/usr/bin/v4l2-ctl", "-d", CAMERA, "-C", "exposure_dynamic_framerate"],
        text=True).strip()
    match = re.fullmatch(r"exposure_dynamic_framerate:\s*([01])", output)
    if not match:
        raise RuntimeError("Unexpected V4L2 control response: " + output)
    return int(match.group(1))


@contextmanager
def exposure_control(fixed):
    info = {"requested_fixed_framerate": fixed,
            "original_dynamic_framerate": dynamic_framerate()}
    if fixed:
        subprocess.run(["/usr/bin/v4l2-ctl", "-d", CAMERA, "-c",
                        "exposure_dynamic_framerate=0"], check=True)
    try:
        info["during_dynamic_framerate"] = dynamic_framerate()
        yield info
    finally:
        if fixed:
            subprocess.run(["/usr/bin/v4l2-ctl", "-d", CAMERA, "-c",
                            "exposure_dynamic_framerate=" +
                            str(info["original_dynamic_framerate"])], check=True)
        info["restored_dynamic_framerate"] = dynamic_framerate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixed-exposure-fps", action="store_true",
                        help="temporarily disable automatic exposure frame-rate reduction")
    args = parser.parse_args()
    if not 2 <= args.seconds <= 120:
        parser.error("seconds must be 2–120")
    if args.output.exists():
        parser.error("choose a new output path")
    with exposure_control(args.fixed_exposure_fps) as exposure:
        with tempfile.TemporaryDirectory(prefix="p16-v4l2-cadence-") as folder:
            video = Path(folder) / "camera.mkv"
            command = ["/usr/bin/ffmpeg", "-hide_banner", "-nostdin",
                       "-f", "v4l2", "-input_format", "mjpeg",
                       "-video_size", "1280x720", "-framerate", "30",
                       "-i", CAMERA, "-t", str(args.seconds), "-c:v", "copy",
                       "-fps_mode", "passthrough", "-an", "-f", "matroska",
                       str(video)]
            started = time.monotonic()
            process = subprocess.run(command, capture_output=True, text=True,
                                     timeout=args.seconds + 45, check=False)
            elapsed = round(time.monotonic() - started, 3)
            if process.returncode:
                raise RuntimeError(process.stderr[-5000:])
            stream = SOAK.video_stream(video)
            timing = SOAK.frame_timing(video)
            frames = int(stream["nb_read_frames"])
            lines = [line.strip() for line in process.stderr.replace("\r", "\n").splitlines()]
            summary = [line for line in lines if re.search(r"\bframe=\s*\d+", line)]
            result = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "device": CAMERA,
                "path": "V4L2 MJPEG packet copy; no Vulkan or other video encoder",
                "requested_seconds": args.seconds,
                "record_elapsed_seconds": elapsed,
                "source": stream,
                "frame_timing": timing,
                "ffmpeg_final_progress": summary[-1] if summary else None,
                "ffmpeg_warning_lines": [line for line in lines if re.search(
                    r"warning|error|drop|corrupt|invalid", line, re.I)][-25:],
                "camera_pixels_retained": False,
                # FFmpeg -t may include the frame exactly at the duration edge.
                "exact_30fps_cadence": frames in (args.seconds * 30,
                                                  args.seconds * 30 + 1) and
                                       timing["gaps_over_50ms"] == 0 and
                                       timing["nonpositive_gaps"] == 0,
            }
            result["sustained_30fps_without_corruption"] = (
                args.seconds * 30 - 1 <= frames <= args.seconds * 31 and
                timing["gaps_over_50ms"] == 0 and
                timing["nonpositive_gaps"] == 0 and
                not any("corrupt" in line.lower() for line in
                        result["ffmpeg_warning_lines"]))
            exposure["after_capture_dynamic_framerate"] = dynamic_framerate()
    result["exposure_control"] = exposure
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"frames": frames, "gaps_over_50ms": timing["gaps_over_50ms"],
                      "exact_30fps_cadence": result["exact_30fps_cadence"],
                      "sustained_30fps_without_corruption":
                      result["sustained_30fps_without_corruption"],
                      "control_restored": exposure["restored_dynamic_framerate"] ==
                      exposure["original_dynamic_framerate"]}))
    return 0 if result["sustained_30fps_without_corruption"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
