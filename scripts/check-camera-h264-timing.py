#!/usr/bin/env python3
"""Measure real P16 camera to H.264 Vulkan frame and timestamp retention."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


spec = importlib.util.spec_from_file_location(
    "camera_av1_common", Path(__file__).with_name("check-camera-av1-vulkan.py"))
COMMON = importlib.util.module_from_spec(spec)
spec.loader.exec_module(COMMON)


def run(command, timeout=150, env=None):
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=timeout, check=False, env=env)


def count(pattern, text):
    matches = re.findall(pattern, text)
    return int(matches[-1]) if matches else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--timebase", choices=("default", "1/1000000"),
                        default="default")
    parser.add_argument("--recorder", type=Path,
                        help="test an extracted or installed p16-record-camera-vulkan command")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    if not 2 <= args.seconds <= 120:
        parser.error("--seconds must be from 2 to 120")
    if not Path(COMMON.CAMERA).exists():
        parser.error("P16 RGB camera unavailable")
    if args.recorder and not args.recorder.is_file():
        parser.error("recorder executable unavailable")
    if args.recorder and args.timebase != "default":
        parser.error("the recorder defines its own encoder time base")
    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "driver": run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                       "--format=csv,noheader"]).stdout.strip(),
        "ffmpeg_sha256": COMMON.digest("/usr/bin/ffmpeg"),
        "requested_seconds": args.seconds,
        "encoder_timebase": args.timebase,
        "camera": COMMON.CAMERA,
        "camera_pixels_or_recording_retained": False,
    }
    if args.recorder:
        report["recorder_sha256"] = COMMON.digest(args.recorder)
        report["recorder_microsecond_timebase_option"] = (
            "-enc_time_base 1/1000000" in args.recorder.read_text())
        report["encoder_timebase"] = "recorder-defined"
    with COMMON.camera_framerate(not args.recorder) as control, \
            tempfile.TemporaryDirectory(prefix="p16-camera-h264-timing-") as folder:
        video = Path(folder) / "camera.mkv"
        ffreport = Path(folder) / "ffmpeg-report.log"
        if args.recorder:
            command = [str(args.recorder.resolve()), "--fixed-fps",
                       str(args.seconds), str(video)]
            env = os.environ.copy()
            env["FFREPORT"] = f"file={ffreport}:level=48"
        else:
            command = ["/usr/bin/ffmpeg", "-hide_banner", "-nostdin", "-loglevel",
                       "verbose", "-init_hw_device", "vulkan=vk:0",
                       "-filter_hw_device", "vk", "-f", "v4l2",
                       "-input_format", "mjpeg", "-video_size", "1280x720",
                       "-framerate", "30", "-i", COMMON.CAMERA,
                       "-t", str(args.seconds), "-vf", "format=nv12,hwupload",
                       "-c:v", "h264_vulkan"]
            if args.timebase != "default":
                command.extend(("-enc_time_base", args.timebase))
            command.extend(("-fps_mode", "passthrough", "-f", "matroska", "-n",
                            str(video)))
            env = None
        started = time.monotonic()
        encoded = run(command, timeout=args.seconds + 45, env=env)
        encoder_log = (ffreport.read_text(errors="replace")
                       if args.recorder and ffreport.exists() else encoded.stderr)
        report["encode_wall_s"] = round(time.monotonic() - started, 3)
        report["encoder_exit_code"] = encoded.returncode
        report["encoder_stderr_tail"] = (encoder_log[-900:]
                                          .replace(folder, "$WORKDIR")
                                          .replace(str(Path.home()), "$HOME")
                                          .replace(str(args.recorder.parent), "$RECORDER_DIR")
                                          if args.recorder else
                                          encoder_log[-900:].replace(folder, "$WORKDIR")
                                          .replace(str(Path.home()), "$HOME"))
        report["input_frames"] = count(
            r"Input stream #0:0 \(video\): \d+ packets read \([^)]*\); (\d+) frames decoded",
            encoder_log)
        report["output_frames"] = count(
            r"Output stream #0:0 \(video\): (\d+) frames encoded",
            encoder_log)
        report["reported_dup"] = count(r"dup=\s*(\d+)", encoder_log)
        report["reported_drop"] = count(r"drop=\s*(\d+)", encoder_log)
        if encoded.returncode == 0:
            probe = run(["/usr/bin/ffprobe", "-v", "error", "-select_streams",
                         "v:0", "-count_frames", "-show_entries",
                         "stream=codec_name,profile,width,height,has_b_frames,nb_read_frames:packet=pts_time,dts_time",
                         "-of", "json", str(video)])
            if probe.returncode:
                raise RuntimeError("H.264 packet probe failed")
            metadata = json.loads(probe.stdout)
            frame_probe = run(["/usr/bin/ffprobe", "-v", "error", "-select_streams",
                               "v:0", "-show_entries",
                               "frame=best_effort_timestamp_time,pict_type",
                               "-of", "json", str(video)])
            if frame_probe.returncode:
                raise RuntimeError("H.264 decoded-frame probe failed")
            stream = metadata["streams"][0]
            pts = [float(item["pts_time"]) for item in metadata["packets"]]
            dts = [float(item["dts_time"]) for item in metadata["packets"]
                   if "dts_time" in item]
            frames = json.loads(frame_probe.stdout).get("frames", [])
            frame_pts = [float(item["best_effort_timestamp_time"]) for item in frames
                         if "best_effort_timestamp_time" in item]
            gaps = [b - a for a, b in zip(frame_pts, frame_pts[1:])]
            report.update({
                "stream": stream,
                "packet_count": len(pts),
                "packet_pts_span_s": round(pts[-1] - pts[0], 3),
                "nonincreasing_packet_pts_count": sum(b <= a for a, b in zip(pts, pts[1:])),
                "packet_dts_count": len(dts),
                "nonincreasing_packet_dts_count": sum(b <= a for a, b in zip(dts, dts[1:])),
                "decoded_frame_pts_count": len(frame_pts),
                "nonincreasing_decoded_pts_count": sum(gap <= 0 for gap in gaps),
                "decoded_gaps_over_50ms": sum(gap > 0.05 for gap in gaps),
                "min_decoded_pts_gap_s": round(min(gaps), 3),
                "max_decoded_pts_gap_s": round(max(gaps), 3),
                "b_frame_count": sum(item.get("pict_type") == "B" for item in frames),
                "first_packet_pts_s": [round(value, 3) for value in pts[:12]],
                "first_packet_dts_s": [round(value, 3) for value in dts[:12]],
                "first_decoded_frame_pts_s": [round(value, 3) for value in frame_pts[:12]],
                "bitstream_bytes": video.stat().st_size,
                "bitstream_sha256": COMMON.digest(video),
            })
            decoded = run(["/usr/bin/ffmpeg", "-v", "error", "-c:v", "h264",
                           "-i", str(video), "-fps_mode", "passthrough",
                           "-f", "framemd5", "-"], timeout=120)
            hashes = re.findall(
                r"^0,\s*\d+,\s*\d+,\s*\d+,\s*\d+,\s*([0-9a-f]{32})$",
                decoded.stdout, re.MULTILINE)
            report.update({"software_decode_exit_code": decoded.returncode,
                           "software_decoded_frames": len(hashes),
                           "distinct_decoded_frame_hashes": len(set(hashes)),
                           "software_decode_stderr_tail": decoded.stderr[-500:]})
    report["camera_dynamic_framerate_control"] = control
    n = report.get("packet_count")
    delta = (report["input_frames"] - report["output_frames"]
             if report["input_frames"] is not None and report["output_frames"] is not None
             else None)
    report["input_frames_beyond_timed_output"] = delta
    report["strict_input_frame_retention_qualified"] = delta == 0
    report["checks"] = {
        "encoder": report["encoder_exit_code"] == 0,
        "timed_input_boundary_at_most_one_frame": delta in (0, 1),
        "encoded_output_accounting": n is not None and report["output_frames"] == n,
        "h264_720p": report.get("stream", {}).get("codec_name") == "h264" and
            report.get("stream", {}).get("width") == 1280 and
            report.get("stream", {}).get("height") == 720,
        "monotonic_packet_dts": report.get("nonincreasing_packet_dts_count") == 0 and
            report.get("packet_dts_count", 0) >= n - 2,
        "monotonic_decoded_frame_pts": report.get("nonincreasing_decoded_pts_count") == 0 and
            report.get("decoded_frame_pts_count") == n,
        "software_decode_complete": report.get("software_decode_exit_code") == 0 and
            report.get("software_decoded_frames") == n,
        "varying_camera_frames": n is not None and
            report.get("distinct_decoded_frame_hashes", 0) > n * 0.9,
        "camera_control_restored": control["before"] == control["after"],
    }
    if args.recorder:
        report["checks"]["recorder_microsecond_timebase_option"] = (
            report["recorder_microsecond_timebase_option"])
    report["pass"] = all(report["checks"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "input": report["input_frames"],
                      "output": report["output_frames"], "packets": n,
                      "packet_pts_reorders": report.get("nonincreasing_packet_pts_count"),
                      "nonincreasing_dts": report.get("nonincreasing_packet_dts_count"),
                      "nonincreasing_decoded_pts": report.get("nonincreasing_decoded_pts_count"),
                      "b_frames": report.get("b_frame_count"),
                      "decoded": report.get("software_decoded_frames"),
                      "control_restored": report["checks"]["camera_control_restored"]}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
