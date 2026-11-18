#!/usr/bin/env python3
"""Check real P16 camera AV1 timing and complete software decode."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "camera_av1_common", HERE / "check-camera-av1-vulkan.py")
COMMON = importlib.util.module_from_spec(spec)
spec.loader.exec_module(COMMON)


def run(command, timeout=120, env=None):
    return subprocess.run(command, capture_output=True, text=True,
                          check=False, timeout=timeout, env=env)


def count(pattern, text):
    matches = re.findall(pattern, text)
    return int(matches[-1]) if matches else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--encoder-timebase", default="1/1000000",
                        choices=("default", "1/1000000"))
    parser.add_argument("--recorder", type=Path,
                        help="test an extracted or installed p16-record-camera-vulkan command")
    parser.add_argument("--bitrate", choices=("5M", "10M", "20M", "40M"),
                        help="direct FFmpeg only; test one explicit AV1 bitrate")
    parser.add_argument("--qp", type=int, choices=(10, 15, 20, 25, 30),
                        help="direct FFmpeg only; test one explicit AV1 CQP")
    parser.add_argument("--gop", type=int, choices=(1, 10, 30),
                        help="direct FFmpeg only; test AV1 keyframe spacing")
    args = parser.parse_args()
    if args.seconds < 2 or args.seconds > 120:
        parser.error("--seconds must be from 2 to 120")
    if args.output.exists():
        parser.error("choose a new output path")
    if not Path(COMMON.CAMERA).exists():
        parser.error("internal P16 RGB camera is unavailable")
    if args.recorder and not args.recorder.is_file():
        parser.error("recorder executable is unavailable")
    if args.recorder and (args.bitrate or args.qp is not None or args.gop):
        parser.error("the packaged recorder does not expose AV1 rate control")
    if args.bitrate and args.qp is not None:
        parser.error("choose either bitrate or CQP")
    report = {"captured_at": datetime.now(timezone.utc).isoformat(),
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
              "driver": run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                             "--format=csv,noheader"]).stdout.strip(),
              "ffmpeg_sha256": COMMON.digest("/usr/bin/ffmpeg"),
              "requested_seconds": args.seconds,
              "encoder_timebase": args.encoder_timebase,
              "bitrate_option": args.bitrate,
              "qp_option": args.qp,
              "gop_option": args.gop,
              "camera": COMMON.CAMERA,
              "camera_pixels_or_recording_retained": False,
              "default_av1_rate_control": args.bitrate is None and args.qp is None}
    if args.recorder:
        report["recorder_sha256"] = COMMON.digest(args.recorder)
        report["recorder_manages_fixed_fps"] = True
        report["recorder_microsecond_timebase_option"] = (
            "-enc_time_base 1/1000000" in args.recorder.read_text())
        report["recorder_all_intra_option"] = "-g 1" in args.recorder.read_text()
        report["encoder_timebase"] = "recorder-defined"
    with COMMON.camera_framerate(not args.recorder) as control, \
            tempfile.TemporaryDirectory(prefix="p16-camera-av1-timing-") as directory:
        work = Path(directory)
        video = work / "camera.mkv"
        ivf = work / "camera.ivf"
        ffreport = work / "ffmpeg-report.log"
        if args.recorder:
            command = [str(args.recorder.resolve()), "--fixed-fps", "--av1",
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
                       "-c:v", "av1_vulkan"]
            if args.encoder_timebase != "default":
                command.extend(("-enc_time_base", args.encoder_timebase))
            if args.bitrate:
                command.extend(("-b:v", args.bitrate))
            if args.qp is not None:
                command.extend(("-rc_mode", "cqp", "-qp", str(args.qp)))
            if args.gop:
                command.extend(("-g", str(args.gop)))
            command.extend(("-fps_mode", "passthrough", "-f", "matroska",
                            "-n", str(video)))
            env = None
        started = time.monotonic()
        encoded = run(command, timeout=args.seconds + 45, env=env)
        encoder_log = (ffreport.read_text(errors="replace")
                       if args.recorder and ffreport.exists() else encoded.stderr)
        report["encode_wall_s"] = round(time.monotonic() - started, 3)
        report["encoder_exit_code"] = encoded.returncode
        report["encoder_stderr_tail"] = (encoder_log[-900:]
                                         .replace(str(work), "$WORKDIR")
                                         .replace(str(Path.home()), "$HOME"))
        report["input_frames"] = count(
            r"Input stream #0:0 \(video\): \d+ packets read \([^)]*\); (\d+) frames decoded",
            encoder_log)
        report["output_frames"] = count(
            r"Output stream #0:0 \(video\): (\d+) frames encoded",
            encoder_log)
        if encoded.returncode == 0:
            probe = run(["/usr/bin/ffprobe", "-v", "error",
                         "-select_streams", "v:0", "-count_frames",
                         "-show_entries",
                         "stream=codec_name,profile,width,height,time_base,nb_read_frames:packet=pts_time",
                         "-of", "json", str(video)])
            if probe.returncode:
                raise RuntimeError("AV1 Matroska probe failed")
            metadata = json.loads(probe.stdout)
            stream = metadata["streams"][0]
            pts = [float(item["pts_time"]) for item in metadata["packets"]]
            gaps = [b - a for a, b in zip(pts, pts[1:])]
            report.update({"stream": stream, "packet_count": len(pts),
                           "packet_pts_span_s": round(pts[-1] - pts[0], 3),
                           "nonincreasing_pts_count": sum(gap <= 0 for gap in gaps),
                           "gaps_over_50ms": sum(gap > 0.05 for gap in gaps),
                           "min_pts_gap_s": round(min(gaps), 3),
                           "max_pts_gap_s": round(max(gaps), 3),
                           "bitstream_bytes": video.stat().st_size,
                           "bitstream_sha256": COMMON.digest(video)})
            decoded = run(["/usr/bin/ffmpeg", "-v", "error", "-c:v",
                           "libdav1d", "-i", str(video), "-fps_mode",
                           "passthrough", "-f", "framemd5", "-"], timeout=120)
            hashes = re.findall(
                r"^0,\s*\d+,\s*\d+,\s*\d+,\s*\d+,\s*([0-9a-f]{32})$",
                decoded.stdout, re.MULTILINE)
            report.update({"dav1d_exit_code": decoded.returncode,
                           "dav1d_frames": len(hashes),
                           "distinct_decoded_frame_hashes": len(set(hashes)),
                           "dav1d_stderr_tail": decoded.stderr[-500:]})
            remux = run(["/usr/bin/ffmpeg", "-v", "error", "-i", str(video),
                         "-c", "copy", "-f", "ivf", str(ivf)])
            if remux.returncode:
                raise RuntimeError("AV1 IVF remux failed")
            aom = run(["/usr/bin/aomdec", "--noblit", "--progress", "--summary",
                       str(ivf)], timeout=120)
            report.update({"libaom_exit_code": aom.returncode,
                           "libaom_frames": count(
                               r"(\d+) decoded frames/\d+ showed frames",
                               aom.stderr)})
    report["camera_dynamic_framerate_control"] = control
    n = report.get("packet_count")
    frame_delta = (report["input_frames"] - report["output_frames"]
                   if report["input_frames"] is not None and
                   report["output_frames"] is not None else None)
    report["input_frames_beyond_timed_output"] = frame_delta
    report["strict_input_frame_retention_qualified"] = frame_delta == 0
    report["checks"] = {
        "encoder": report["encoder_exit_code"] == 0,
        "timed_input_boundary_at_most_one_frame": frame_delta in (0, 1),
        "encoded_output_accounting": n is not None and
            report["output_frames"] == n,
        "av1_main_720p": report.get("stream", {}).get("codec_name") == "av1" and
            report.get("stream", {}).get("profile") == "Main" and
            report.get("stream", {}).get("width") == 1280 and
            report.get("stream", {}).get("height") == 720,
        "monotonic_packet_pts": report.get("nonincreasing_pts_count") == 0,
        "dav1d_complete": report.get("dav1d_exit_code") == 0 and
            report.get("dav1d_frames") == n,
        "libaom_complete": report.get("libaom_exit_code") == 0 and
            report.get("libaom_frames") == n,
        "varying_camera_frames": n is not None and
            report.get("distinct_decoded_frame_hashes", 0) > n * 0.9,
        "camera_control_restored": control["before"] == control["after"],
    }
    if args.recorder:
        report["checks"]["recorder_microsecond_timebase_option"] = (
            report["recorder_microsecond_timebase_option"])
        report["checks"]["recorder_all_intra_option"] = (
            report["recorder_all_intra_option"])
    report["pass"] = all(report["checks"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "input": report["input_frames"],
                      "output": report["output_frames"], "packets": n,
                      "nonincreasing_pts": report.get("nonincreasing_pts_count"),
                      "dav1d": report.get("dav1d_frames"),
                      "libaom": report.get("libaom_frames"),
                      "camera_control_restored": report["checks"]["camera_control_restored"]}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
