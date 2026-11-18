#!/usr/bin/env python3
"""Test timed 12-bit 4:4:4 HEVC playback through N1X VA-API and FFplay Vulkan."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def run(command, *, timeout=30, env=None):
    return subprocess.run(command, capture_output=True, text=True, check=True,
                          timeout=timeout, env=env)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def play(binary, fixture, work, evidence, label, decoder):
    command = [str(binary), "-hide_banner", "-autoexit", "-loglevel", "verbose",
               "-enable_vulkan", "-an"]
    command += (["-vcodec", "hevc_cuvid"] if decoder == "cuvid" else
                ["-hwaccel", "vaapi"])
    command.append(str(fixture))
    started = time.monotonic()
    result = run(command, timeout=18, env={**os.environ,
                 "SDL_VIDEODRIVER": "wayland", "LIBVA_DRIVER_NAME": "nvidia",
                 "NVD_BACKEND": "direct"})
    elapsed = time.monotonic() - started
    log = result.stdout + "\n" + result.stderr
    cleaned = log.replace(str(work), "$WORKDIR").replace(str(Path.home()), "$HOME")
    cleaned = re.sub(r"Device UUID:\s*[0-9A-Fa-f:]+", "Device UUID: [redacted]", cleaned)
    (evidence / f"{label}-{decoder}.log").write_text(
        "\n".join(line.rstrip() for line in cleaned.replace("\r", "\n").splitlines()) + "\n")
    surface = re.search(r"\[ffplay_buffer[^\n]*pixfmt:(\w+)", log)
    clocks = [float(value) for value in re.findall(r"(\d+\.\d+) M-V:", log)]
    checks = {
        "vulkan_renderer": "Initialized libplacebo" in log and
                           "Device 0 selected: NVIDIA RTX Spark N1X" in log,
        "hardware_decoder": ("VA-API NVDEC driver [direct backend]" in log
                             if decoder == "vaapi" else
                             "CUVID capabilities for hevc_cuvid" in log),
        "expected_renderer_input": surface is not None and
                                   surface.group(1) == ("vaapi" if decoder == "vaapi"
                                                        else "yuv444p12msble"),
        "timed_to_end": bool(clocks) and max(clocks) >= 2.7,
        "no_renderer_error": not any(value in log for value in
                                     ("pl_map_avframe_ex failed", "pl_render_image failed",
                                      "SDL_PIXELFORMAT_IYUV")),
    }
    return {"status": "pass" if all(checks.values()) else "fail",
            "binary": str(binary).replace(str(Path.home()), "$HOME"),
            "sha256": sha256(binary), "decoder": decoder,
            "elapsed_s": round(elapsed, 3), "last_video_clock_s": max(clocks, default=None),
            "renderer_input": surface.group(1) if surface else None, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x265-12", type=Path, required=True)
    parser.add_argument("--installed-ffplay", type=Path, required=True)
    parser.add_argument("--candidate-ffplay", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="n1x-hevc44412-play-") as temporary:
        work = Path(temporary)
        raw, hevc, fixture = (work / name for name in
                              ("source.yuv", "source.hevc", "timed.mkv"))
        run(["/usr/bin/ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             "testsrc2=size=320x180:rate=10", "-frames:v", "30", "-pix_fmt",
             "yuv444p12le", "-f", "rawvideo", "-y", str(raw)])
        run([str(args.x265_12), "--input", str(raw), "--input-res", "320x180",
             "--fps", "10", "--input-depth", "12", "--input-csp", "i444",
             "--frames", "30", "--bframes", "0", "--preset", "ultrafast",
             "--crf", "22", "--output", str(hevc)])
        run(["/usr/bin/ffmpeg", "-v", "error", "-r", "10", "-i", str(hevc),
             "-c:v", "copy", "-bsf:v",
             "setts=pts=N:dts=N:duration=1:time_base=1/10", "-y", str(fixture)])
        probe = json.loads(run(["/usr/bin/ffprobe", "-v", "error", "-select_streams",
                               "v:0", "-count_frames", "-show_entries",
                               "stream=profile,pix_fmt,nb_read_frames:packet=pts_time,dts_time,duration_time",
                               "-of", "json", str(fixture)]).stdout)
        stream, packets = probe["streams"][0], probe["packets"]
        if (stream.get("profile"), stream.get("pix_fmt"),
            stream.get("nb_read_frames")) != ("Rext", "yuv444p12le", "30"):
            raise RuntimeError(f"wrong fixture: {stream}")
        if len(packets) != 30 or any(
                abs(float(packet[key]) - (index / 10 if key != "duration_time" else .1)) > .001
                for index, packet in enumerate(packets)
                for key in ("pts_time", "dts_time", "duration_time")):
            raise RuntimeError("fixture timestamps are not continuous 10 fps")
        results = [play(binary, fixture, work, args.output_dir, label, decoder)
                   for label, binary in (("installed", args.installed_ffplay),
                                         ("candidate", args.candidate_ffplay))
                   for decoder in ("cuvid", "vaapi")]
        report = {"status": "pass" if all(item["status"] == "pass" for item in results)
                  else "fail", "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
                  "driver": run(["nvidia-smi", "--query-gpu=driver_version",
                                 "--format=csv,noheader"]).stdout.strip(),
                  "fixture": {"sha256": sha256(fixture), "frames": 30,
                              "format": "HEVC RExt yuv444p12le", "fps": 10,
                              "duration_s": 3, "timestamp_filter":
                              "setts=pts=N:dts=N:duration=1:time_base=1/10"},
                  "results": results,
                  "limit": "Player input and EOF are verified; display color accuracy, actual output bit depth and zero-copy are not measured."}
        (args.output_dir / "hevc44412-vaapi-playback.json").write_text(
            json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        if report["status"] != "pass":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
