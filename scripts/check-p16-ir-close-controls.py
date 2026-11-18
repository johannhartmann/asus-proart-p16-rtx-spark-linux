#!/usr/bin/env python3
"""Compare two ordinary V4L2 IR captures with mpv's recorded close warning.

Both controls consume 45 GREY frames and discard pixels immediately. They
must be run sequentially because the UVC node is exclusive while streaming.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import signal
import subprocess
import time


CAMERA = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.2-video-index0"
FRAMES = 45


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                            check=False)
    return {"command": command, "exit_code": result.returncode,
            "stdout_tail": result.stdout[-1200:],
            "stderr_tail": result.stderr[-1600:],
            "v4l2_close_warning": "Some buffers are still owned by the caller on close"
                                  in result.stdout + result.stderr,
            "qbuf_bad_fd": "ioctl(VIDIOC_QBUF): Bad file descriptor"
                           in result.stdout + result.stderr}


def interrupted_ffmpeg(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    try:
        time.sleep(3)
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    return {"command": command, "signal": "SIGINT after 3 seconds",
            "exit_code": process.returncode,
            "stdout_tail": stdout[-1200:], "stderr_tail": stderr[-1600:],
            "v4l2_close_warning": "Some buffers are still owned by the caller on close"
                                  in stdout + stderr,
            "qbuf_bad_fd": "ioctl(VIDIOC_QBUF): Bad file descriptor" in stdout + stderr,
            "signal_handled": "Exiting normally, received signal 2." in stderr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new evidence path")
    if not Path(CAMERA).exists():
        parser.error("P16 IR camera is absent")
    v4l2 = run(["/usr/bin/v4l2-ctl", "-d", CAMERA, "--stream-mmap=4",
                f"--stream-count={FRAMES}", "--stream-to=/dev/null", "--stream-poll"])
    ffmpeg = run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "info",
                  "-f", "v4l2", "-input_format", "gray", "-video_size", "360x360",
                  "-framerate", "15", "-i", CAMERA, "-frames:v", str(FRAMES),
                  "-f", "null", "-"])
    interrupted = interrupted_ffmpeg([
        "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "info",
        "-f", "v4l2", "-input_format", "gray", "-video_size", "360x360",
        "-framerate", "15", "-i", CAMERA, "-f", "null", "-"])
    v4l2["frame_markers"] = v4l2["stdout_tail"].count("<") + v4l2["stderr_tail"].count("<")
    v4l2["reported_fps"] = re.findall(r"\b\d+(?:\.\d+)? fps\b",
                                     v4l2["stdout_tail"] + v4l2["stderr_tail"])
    ffmpeg["reported_final_frames"] = [int(value) for value in re.findall(
        r"frame=\s*(\d+)", ffmpeg["stdout_tail"] + ffmpeg["stderr_tail"])]
    interrupted["reported_frames"] = [int(value) for value in re.findall(
        r"frame=\s*(\d+)", interrupted["stdout_tail"] + interrupted["stderr_tail"])]
    report = {"captured_at": datetime.now(timezone.utc).isoformat(),
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
              "camera": CAMERA, "format": "GREY 360x360 15 fps",
              "expected_frames_each": FRAMES,
              "v4l2_ctl": v4l2, "ffmpeg": ffmpeg,
              "ffmpeg_sigint": interrupted,
              "camera_pixels_or_video_retained": False,
              "mpv_comparison": "ir-mpv-preview-kernel38.json"}
    report["pass"] = (v4l2["exit_code"] == 0 and v4l2["frame_markers"] == FRAMES and
                      ffmpeg["exit_code"] == 0 and
                      bool(ffmpeg["reported_final_frames"]) and
                      ffmpeg["reported_final_frames"][-1] == FRAMES and
                      interrupted["exit_code"] == 255 and interrupted["signal_handled"] and
                      bool(interrupted["reported_frames"]) and
                      interrupted["reported_frames"][-1] >= 30 and
                      not any(result["v4l2_close_warning"] or result["qbuf_bad_fd"]
                              for result in (v4l2, ffmpeg, interrupted)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "v4l2_frames": v4l2["frame_markers"],
                      "ffmpeg_frames": ffmpeg["reported_final_frames"][-1:],
                      "ffmpeg_sigint_frames": interrupted["reported_frames"][-1:]},
                     separators=(",", ":")))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
