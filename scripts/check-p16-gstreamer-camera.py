#!/usr/bin/env python3
"""Verify the installed P16 camera to GStreamer Vulkan Video recorder."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def run(args):
    return subprocess.run(args, text=True, capture_output=True, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    command = Path("/usr/bin/p16-record-camera-gstreamer")
    with tempfile.TemporaryDirectory(prefix="p16-gst-camera-") as directory:
        video = Path(directory) / "camera.h264"
        recorded = run([str(command), "2", str(video)])
        log = recorded.stdout + recorded.stderr
        (args.evidence / "gstreamer-camera-vulkan.log").write_text(log)
        probe = json.loads(run(["ffprobe", "-v", "error", "-f", "h264", "-select_streams", "v:0",
                                "-count_frames", "-show_entries",
                                "stream=codec_name,profile,width,height,nb_read_frames", "-of", "json",
                                str(video)]).stdout)
        hashes = [line.split(",")[-1].strip() for line in
                  run(["ffmpeg", "-v", "error", "-f", "h264", "-i", str(video),
                       "-vf", "scale=32:18,format=gray", "-f", "framemd5", "-"]).stdout.splitlines()
                  if line and not line.startswith("#")]
        result = {"package": run(["pacman", "-Q", "p16-media-tools"]).stdout.strip(),
                  "recorderSha256": hashlib.sha256(command.read_bytes()).hexdigest(),
                  "recordingSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                  "probe": probe, "decodedFrameHashes": len(hashes),
                  "uniqueDownscaledFrameHashes": len(set(hashes)),
                  "gstreamerVulkanEncoder": "GstVulkanH264Encoder" in log and
                  "video/x-raw(memory:VulkanImage)" in log,
                  "recordingRetained": False}
        stream = probe["streams"][0]
        result["pass"] = (stream["codec_name"] == "h264" and
                          stream["width"] == 1280 and stream["height"] == 720 and
                          stream["nb_read_frames"] == "60" and len(hashes) == 60 and
                          len(set(hashes)) > 10 and result["gstreamerVulkanEncoder"])
    (args.evidence / "gstreamer-camera-vulkan.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "frames": result["decodedFrameHashes"],
                      "uniqueFrames": result["uniqueDownscaledFrameHashes"]}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
