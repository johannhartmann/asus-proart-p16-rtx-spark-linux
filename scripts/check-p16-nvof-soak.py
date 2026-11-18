#!/usr/bin/env python3
"""Exercise installed NVOFA export on a longer live P16 camera recording."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time


def run(command, timeout):
    return subprocess.run(command, capture_output=True, text=True,
                          check=True, timeout=timeout)


def video_stream(path):
    output = run(["/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-count_frames", "-show_entries",
                  "stream=codec_name,width,height,avg_frame_rate,nb_read_frames",
                  "-of", "json", str(path)], 30)
    return json.loads(output.stdout)["streams"][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error("seconds must be 5–120")
    with tempfile.TemporaryDirectory(prefix="p16-nvof-soak-") as temporary:
        source = Path(temporary) / "camera.mkv"
        exported = Path(temporary) / "interpolated.mkv"
        start = time.monotonic()
        record = run(["/usr/bin/p16-record-camera-vulkan", str(args.seconds),
                      str(source)], args.seconds + 40)
        recorded_seconds = time.monotonic() - start
        source_stream = video_stream(source)
        source_frames = int(source_stream["nb_read_frames"])
        start = time.monotonic()
        export = run(["/usr/bin/p16-interpolate-video", str(source), str(exported),
                      str(source_frames - 1)], max(180, args.seconds * 10))
        export_seconds = time.monotonic() - start
        output_stream = video_stream(exported)
        decode = run(["/usr/bin/ffmpeg", "-v", "error", "-i", str(exported),
                      "-f", "null", "-"], max(120, args.seconds * 5))
        result = {
            "package": run(["/usr/bin/pacman", "-Q", "p16-nvof-tools"], 5).stdout.strip(),
            "camera_record_command": "/usr/bin/p16-record-camera-vulkan",
            "export_command": "/usr/bin/p16-interpolate-video",
            "requested_camera_seconds": args.seconds,
            "record_elapsed_seconds": round(recorded_seconds, 3),
            "export_elapsed_seconds": round(export_seconds, 3),
            "source": source_stream,
            "output": output_stream,
            "nvof_pairs_logged": f"nvof_interpolated_pairs={source_frames - 1}" in
                (export.stdout + export.stderr),
            "vulkan_encoder_logged": "h264_vulkan" in (export.stdout + export.stderr),
            "independent_decode_exit_code": decode.returncode,
            "camera_pixels_retained": False,
        }
        result["pass"] = (source_frames == args.seconds * 30 and
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
