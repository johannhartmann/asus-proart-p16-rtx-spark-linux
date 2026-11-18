#!/usr/bin/env python3
"""Verify the installed mpv renders live P16 IR frames through Wayland/Vulkan."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time


CAMERA = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.2-video-index0"


def request(connection, file, command, request_id):
    connection.sendall((json.dumps({"command": command,
                                    "request_id": request_id}) + "\n").encode())
    while True:
        line = file.readline()
        if not line:
            raise RuntimeError("mpv IPC closed before reply")
        reply = json.loads(line)
        if reply.get("request_id") == request_id:
            return reply


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--direct-demux", action="store_true",
                        help="disable mpv's demux thread and cache to test V4L2 close")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    if not Path(CAMERA).exists():
        parser.error("P16 IR camera is absent")
    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "camera": CAMERA,
        "direct_demux": args.direct_demux,
        "mpv_version": subprocess.run(["/usr/bin/mpv", "--version"],
                                      capture_output=True, text=True,
                                      check=True).stdout.splitlines()[0],
        "camera_pixels_or_video_retained": False,
    }
    with tempfile.TemporaryDirectory(prefix="p16-ir-preview-") as folder:
        work = Path(folder)
        ipc = work / "mpv.sock"
        log = work / "mpv.log"
        command = ["/usr/bin/mpv", "--no-config", "--vo=gpu-next",
                   "--gpu-api=vulkan", "--hwdec=no", "--profile=low-latency",
                   "--demuxer-lavf-format=v4l2",
                   "--demuxer-lavf-o=video_size=360x360,input_format=gray,framerate=15",
                   f"--input-ipc-server={ipc}", f"--log-file={log}"]
        if args.direct_demux:
            command += ["--demuxer-thread=no", "--cache=no"]
        command += [f"av://v4l2:{CAMERA}"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        stdout = ""
        try:
            deadline = time.monotonic() + 12
            while not ipc.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(0.1)
            if not ipc.exists():
                raise RuntimeError("mpv IPC did not start")
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(5)
                connection.connect(str(ipc))
                file = connection.makefile("r", encoding="utf-8")
                try:
                    values = []
                    params = None
                    for i in range(40):
                        frame = request(connection, file, ["get_property", "video-params"],
                                        i * 2 + 1)
                        stamp = request(connection, file, ["get_property", "time-pos"],
                                        i * 2 + 2)
                        if frame.get("error") == "success" and frame.get("data"):
                            params = frame["data"]
                        if (stamp.get("error") == "success" and
                                isinstance(stamp.get("data"), (int, float)) and
                                stamp["data"] > 0):
                            values.append(float(stamp["data"]))
                        if params and len(values) >= 3 and values[-1] - values[0] >= 1.5:
                            break
                        time.sleep(0.2)
                    report["video_params"] = params
                    report["time_pos_samples"] = [round(value, 3) for value in values]
                    request(connection, file, ["quit"], 1001)
                finally:
                    file.close()
            stdout, _ = process.communicate(timeout=8)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
        log_text = log.read_text(errors="replace") if log.exists() else ""
        report["mpv_exit_code"] = process.returncode
        report["renderer_selected"] = "VO: [gpu-next] 360x360 gray" in stdout
        report["vulkan_device_logged"] = "NVIDIA RTX Spark N1X" in log_text
        report["v4l2_close_warning"] = "Some buffers are still owned by the caller on close" in stdout
        report["v4l2_qbuf_after_close_count"] = len(re.findall(
            r"ioctl\(VIDIOC_QBUF\): Bad file descriptor", stdout))
        check = subprocess.run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel",
                                "error", "-f", "v4l2", "-input_format", "gray",
                                "-video_size", "360x360", "-framerate", "15",
                                "-i", CAMERA, "-frames:v", "3", "-f", "null", "-"],
                               capture_output=True, text=True, timeout=15)
        report["camera_reopen_exit_code"] = check.returncode
        report["camera_reopen_stderr_tail"] = check.stderr[-300:]
    stamps = report.get("time_pos_samples", [])
    params = report.get("video_params") or {}
    report["pass"] = (report["mpv_exit_code"] == 0 and
                      report["renderer_selected"] and
                      report["vulkan_device_logged"] and
                      params.get("w") == 360 and params.get("h") == 360 and
                      params.get("pixelformat") == "gray" and
                      len(stamps) >= 3 and stamps[-1] - stamps[0] >= 1.5 and
                      report["camera_reopen_exit_code"] == 0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "renderer": report["renderer_selected"],
                      "video": report["video_params"], "samples": stamps,
                      "reopen": report["camera_reopen_exit_code"]}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
