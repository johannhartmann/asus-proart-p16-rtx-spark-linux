#!/usr/bin/env python3
"""Exercise installed NVOFA export on a longer live P16 camera recording."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time


def run(command, timeout):
    return subprocess.run(command, capture_output=True, text=True,
                          check=True, timeout=timeout)


def video_stream(path, timeout=30):
    output = run(["/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-count_frames", "-show_entries",
                  "stream=codec_name,width,height,avg_frame_rate,nb_read_frames",
                  "-of", "json", str(path)], timeout)
    return json.loads(output.stdout)["streams"][0]


def frame_timing(path, timeout=30):
    output = run(["/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "frame=best_effort_timestamp_time",
                  "-of", "csv=p=0", str(path)], timeout)
    timestamps = [float(line.strip().split(",")[0]) for line in
                  output.stdout.splitlines() if line.strip() and line.strip() != "N/A"]
    gaps = [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]
    large_gaps = [{"after_frame_index": index,
                   "after_pts_seconds": round(timestamps[index], 6),
                   "gap_seconds": round(gap, 6),
                   "nominal_missing_30fps_frames": max(0, round(gap * 30) - 1)}
                  for index, gap in enumerate(gaps) if gap > 0.05]
    return {
        "frames_with_pts": len(timestamps),
        "first_pts_seconds": timestamps[0] if timestamps else None,
        "last_pts_seconds": timestamps[-1] if timestamps else None,
        "max_gap_seconds": round(max(gaps), 6) if gaps else None,
        "gaps_over_50ms": sum(gap > 0.05 for gap in gaps),
        "large_gap_events": large_gaps[:20],
        "large_gap_events_truncated": len(large_gaps) > 20,
        "nonpositive_gaps": sum(gap <= 0 for gap in gaps),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--record-only", action="store_true",
                        help="measure camera/Vulkan recording without NVOFA export")
    parser.add_argument("--fixed-exposure-fps", action="store_true",
                        help="temporarily disable exposure-driven frame-rate reduction")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error("seconds must be 5–120")
    if args.output.exists():
        parser.error("choose a new output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    control = "exposure_dynamic_framerate"
    camera = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.0-video-index0"

    def dynamic_fps():
        response = run(["/usr/bin/v4l2-ctl", "-d", camera, "-C", control], 5).stdout.strip()
        match = re.fullmatch(r"exposure_dynamic_framerate:\s*([01])", response)
        if not match:
            raise RuntimeError("Unexpected V4L2 control response: " + response)
        return int(match.group(1))

    with tempfile.TemporaryDirectory(prefix="p16-nvof-soak-") as temporary:
        source = Path(temporary) / "camera.mkv"
        exported = Path(temporary) / "interpolated.mkv"
        original_dynamic_fps = dynamic_fps()
        if args.fixed_exposure_fps:
            run(["/usr/bin/v4l2-ctl", "-d", camera, "-c", control + "=0"], 5)
        try:
            during_dynamic_fps = dynamic_fps()
            start = time.monotonic()
            record = run(["/usr/bin/p16-record-camera-vulkan", str(args.seconds),
                          str(source)], args.seconds + 40)
            recorded_seconds = time.monotonic() - start
            after_record_dynamic_fps = dynamic_fps()
        finally:
            if args.fixed_exposure_fps:
                run(["/usr/bin/v4l2-ctl", "-d", camera, "-c",
                     control + "=" + str(original_dynamic_fps)], 5)
        restored_dynamic_fps = dynamic_fps()
        source_stream = video_stream(source, max(45, args.seconds * 2))
        source_timing = frame_timing(source, max(45, args.seconds * 2))
        source_frames = int(source_stream["nb_read_frames"])
        record_warnings = [line.strip() for line in
                           record.stderr.replace("\r", "\n").splitlines()
                           if re.search(r"warning|error|drop|corrupt|invalid", line, re.I)]
        counters = re.findall(r"dup=\s*(\d+)\s+drop=\s*(\d+)", record.stderr)
        # FFmpeg omits both counters from progress when neither has occurred.
        duplicates, dropped = map(int, counters[-1]) if counters else (0, 0)
        encoded_cadence_pass = (args.seconds * 30 - 1 <= source_frames <= args.seconds * 31 and
                                source_timing["gaps_over_50ms"] == 0 and
                                source_timing["nonpositive_gaps"] == 0)
        source_cadence_pass = (encoded_cadence_pass and duplicates == 0 and
                               dropped == 0 and
                               not any("corrupt" in line.lower() for line in record_warnings))
        result = {
            "package": run(["/usr/bin/pacman", "-Q", "p16-nvof-tools"], 5).stdout.strip(),
            "camera_record_command": "/usr/bin/p16-record-camera-vulkan",
            "requested_camera_seconds": args.seconds,
            "record_elapsed_seconds": round(recorded_seconds, 3),
            "source": source_stream,
            "source_frame_timing": source_timing,
            "source_frame_count_exact": source_frames == args.seconds * 30,
            "encoded_cadence_pass": encoded_cadence_pass,
            "source_cadence_pass": source_cadence_pass,
            "ffmpeg_duplicate_frames": duplicates,
            "ffmpeg_dropped_frames": dropped,
            "record_warning_lines": record_warnings[-25:],
            "exposure_control": {
                "requested_fixed_framerate": args.fixed_exposure_fps,
                "original_dynamic_framerate": original_dynamic_fps,
                "during_dynamic_framerate": during_dynamic_fps,
                "after_record_dynamic_framerate": after_record_dynamic_fps,
                "restored_dynamic_framerate": restored_dynamic_fps,
            },
            "camera_pixels_retained": False,
            "record_only": args.record_only,
        }
        if args.record_only:
            result["pass"] = source_cadence_pass
            args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
            return 0 if result["pass"] else 1
        start = time.monotonic()
        export = run(["/usr/bin/p16-interpolate-video", str(source), str(exported),
                      str(source_frames - 1)], max(180, args.seconds * 10))
        export_seconds = time.monotonic() - start
        output_stream = video_stream(exported, max(45, args.seconds * 3))
        decode = run(["/usr/bin/ffmpeg", "-v", "error", "-i", str(exported),
                      "-f", "null", "-"], max(120, args.seconds * 5))
        result.update({
            "export_command": "/usr/bin/p16-interpolate-video",
            "export_elapsed_seconds": round(export_seconds, 3),
            "output": output_stream,
            "nvof_pairs_logged": f"nvof_interpolated_pairs={source_frames - 1}" in
                (export.stdout + export.stderr),
            "vulkan_encoder_logged": "h264_vulkan" in (export.stdout + export.stderr),
            "independent_decode_exit_code": decode.returncode,
        })
        result["pass"] = (source_cadence_pass and
                          source_stream["width"] == output_stream["width"] == 1280 and
                          source_stream["height"] == output_stream["height"] == 720 and
                          output_stream["codec_name"] == "h264" and
                          output_stream["avg_frame_rate"] == "60/1" and
                          int(output_stream["nb_read_frames"]) == 2 * source_frames - 1 and
                          result["nvof_pairs_logged"] and result["vulkan_encoder_logged"])
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
