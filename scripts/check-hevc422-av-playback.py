#!/usr/bin/env python3
"""Qualify timed HEVC 4:2:2 plus audio playback in the isolated CUVID player."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffplay", required=True)
    parser.add_argument("--vulkan", action="store_true",
                        help="require FFplay's libplacebo Vulkan renderer")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="n1x-hevc422-av-") as directory:
        work = Path(directory)
        fixture = work / "hevc422-av.mkv"
        source = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                  "-i", "testsrc2=size=320x180:rate=24", "-f", "lavfi",
                  "-i", "sine=frequency=440:sample_rate=48000", "-t", "6",
                  "-pix_fmt", "yuv422p", "-c:v", "libx265", "-preset", "ultrafast",
                  "-x265-params", "log-level=error", "-c:a", "aac", "-b:a", "96k",
                  "-y", str(fixture)]
        subprocess.run(source, check=True, capture_output=True, timeout=30)
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames",
                                "-show_entries", "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames:format=duration",
                                "-of", "json", str(fixture)], check=True,
                               capture_output=True, text=True, timeout=10)
        metadata = json.loads(probe.stdout)
        video, audio = metadata["streams"]
        if (video.get("codec_name"), video.get("profile"), video.get("pix_fmt"),
            video.get("width"), video.get("height"), video.get("nb_read_frames"),
            audio.get("codec_name")) != ("hevc", "Rext", "yuv422p", 320, 180, "144", "aac"):
            raise RuntimeError(f"wrong fixture metadata: {metadata}")
        command = [args.ffplay, "-hide_banner", "-autoexit", "-loglevel", "verbose"]
        if args.vulkan:
            command.append("-enable_vulkan")
        command += ["-vcodec", "hevc_cuvid", "-volume", "2", str(fixture)]
        start = time.monotonic()
        played = subprocess.run(command, capture_output=True, text=True, check=False,
                                timeout=20, env={**os.environ, "SDL_VIDEODRIVER": "wayland"})
        elapsed = time.monotonic() - start
        log = played.stdout + "\n" + played.stderr
        cleaned = log.replace(str(work), "$WORKDIR").replace(str(Path.home()), "$HOME")
        cleaned = re.sub(r"Device UUID:\s*[0-9A-Fa-f:]+", "Device UUID: [redacted]", cleaned)
        (args.output_dir / "hevc422-av-ffplay.log").write_text(
            "exit_code=" + str(played.returncode) + "\n" +
            "\n".join(line.rstrip() for line in cleaned.replace("\r", "\n").splitlines()) + "\n")
        samples = [(float(pts), float(delta)) for pts, delta in
                   re.findall(r"(\d+\.\d+) A-V:\s*(-?\d+\.\d+)", log)]
        checks = {
            "cuvid_opened": "CUVID capabilities for hevc_cuvid" in log and
                            "Formats: Original: nv16 | HW: nv16 | SW: nv16" in log,
            "audio_opened": "Audio: aac" in log and "ffplay_abuffer" in log,
            "timed_playback": bool(samples) and max(p for p, _ in samples) >= 5.8 and
                              elapsed >= 5.0 and all(abs(d) < 0.1 for _, d in samples),
            "reached_eof": played.returncode == 0,
            "display_chroma_downsampled": "SDL_PIXELFORMAT_IYUV" in log,
            "vulkan_renderer": ("Initialized libplacebo" in log and
                                "Device 0 selected: NVIDIA RTX Spark N1X" in log and
                                "pixfmt:nv16" in log and
                                "auto_scale_0" not in log and
                                "SDL_PIXELFORMAT_IYUV" not in log),
        }
        report = {
            "status": "pass" if all(checks[key] for key in (
                "cuvid_opened", "audio_opened", "timed_playback", "reached_eof")) and
                (not args.vulkan or checks["vulkan_renderer"]) else "fail",
            "machine": "ASUS ProArt P16 H7607BA",
            "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
            "driver": subprocess.check_output(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                text=True, timeout=10).strip(),
            "ffplay": str(args.ffplay).replace(str(Path.home()), "$HOME"),
            "ffplay_sha256": sha256(args.ffplay),
            "renderer_requested": "vulkan" if args.vulkan else "sdl",
            "fixture_sha256": sha256(fixture), "fixture": metadata,
            "elapsed_s": round(elapsed, 3), "av_sample_count": len(samples),
            "av_max_abs_delta_s": round(max((abs(d) for _, d in samples), default=0), 4),
            "checks": checks,
            "limit": ("SDL IYUV output converts 4:2:2 to 4:2:0."
                      if checks["display_chroma_downsampled"] else
                      "Libplacebo receives nv16 without an observed format conversion; final display precision needs separate measurement."),
        }
        (args.output_dir / "hevc422-av-ffplay.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": report["status"], "checks": checks}))
        return int(report["status"] != "pass")


if __name__ == "__main__":
    sys.exit(main())
