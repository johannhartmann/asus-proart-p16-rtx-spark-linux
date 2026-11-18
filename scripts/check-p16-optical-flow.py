#!/usr/bin/env python3
"""Qualify the installed N1X Optical Flow Accelerator with controls and live video."""

import argparse
import hashlib
import json
import random
import subprocess
import tempfile
from pathlib import Path


def run(args, *, input_data=None):
    return subprocess.run(args, input=input_data, capture_output=True, check=True)


def textured_frame(width, height):
    rng = random.Random(42)
    return bytes(rng.randrange(256) for _ in range(width * height))


def shifted(frame, width, height, dx):
    output = bytearray(width * height)
    for row in range(height):
        start = row * width
        output[start + dx:start + width] = frame[start:start + width - dx]
    return bytes(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    binary = Path("/usr/bin/p16-nvof-analyze")
    width, height = 320, 180
    image = textured_frame(width, height)
    static = json.loads(run([str(binary), str(width), str(height), "1"],
                            input_data=image + image).stdout)
    moved = json.loads(run([str(binary), str(width), str(height), "1"],
                           input_data=image + shifted(image, width, height, 8)).stdout)
    with tempfile.TemporaryDirectory(prefix="p16-nvof-") as temporary:
        video = Path(temporary) / "camera.mkv"
        recorder = run(["/usr/bin/p16-record-camera-vulkan", "2", str(video)])
        camera = json.loads(run(["/usr/bin/p16-optical-flow", str(video), "30"]).stdout)
        probe = json.loads(run(["/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-count_frames", "-show_entries", "stream=codec_name,width,height,nb_read_frames",
                                "-of", "json", str(video)]).stdout)
        record_log = (recorder.stdout + recorder.stderr).decode(errors="replace")
        saved_log = record_log.replace(temporary, "$TEMP")
        (args.evidence / "nvof-camera-record.log").write_text(
            "\n".join(line.rstrip() for line in saved_log.splitlines()) + "\n")
        recording_hash = hashlib.sha256(video.read_bytes()).hexdigest()
    result = {"package": run(["/usr/bin/pacman", "-Q", "p16-nvof-tools"]).stdout.decode().strip(),
              "sdkCommit": "edb50da3cf849840d680249aa6dbef248ebce2ca",
              "analyzerSha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "wrapperSha256": hashlib.sha256(Path("/usr/bin/p16-optical-flow").read_bytes()).hexdigest(),
              "staticControl": static,
              "eightPixelTranslation": moved,
              "cameraRecordingSha256": recording_hash,
              "cameraRecordingProbe": probe,
              "cameraAnalysis": camera,
              "cameraRecordingRetained": False}
    fixed = static["pairs"][0]
    translation = moved["pairs"][0]
    stream = probe["streams"][0]
    result["pass"] = (static["pair_count"] == moved["pair_count"] == 1 and
                      fixed["mean_magnitude"] < 0.02 and
                      abs(translation["mean_dx"] - 8) < 0.2 and
                      abs(translation["mean_dy"]) < 0.2 and
                      camera["backend"] == "NVIDIA NVOFA CUDA" and
                      camera["pair_count"] == 30 and
                      camera["mean_magnitude"] > 0.01 and
                      stream["codec_name"] == "h264" and
                      stream["nb_read_frames"] == "60")
    (args.evidence / "nvof-application.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "staticMagnitude": fixed["mean_magnitude"],
                      "shiftDx": translation["mean_dx"],
                      "cameraPairs": camera["pair_count"]}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
