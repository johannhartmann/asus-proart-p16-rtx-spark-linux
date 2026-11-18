#!/usr/bin/env python3
"""Compare N1X Vulkan H.264/HEVC/AV1 output with a shared NV12 source."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


FRAMES = 120
SIZE = "1280x720"
FPS = "30"
CASES = {
    "x264_crf18": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"],
    "h264_vulkan_default": ["-c:v", "h264_vulkan"],
    "hevc_vulkan_default": ["-c:v", "hevc_vulkan"],
    "av1_default": ["-c:v", "av1_vulkan"],
    "av1_default_g1": ["-c:v", "av1_vulkan", "-g", "1"],
    "av1_default_g10": ["-c:v", "av1_vulkan", "-g", "10"],
    "av1_default_g30": ["-c:v", "av1_vulkan", "-g", "30"],
    "av1_cqp25_g30": ["-c:v", "av1_vulkan", "-rc_mode", "cqp", "-qp", "25", "-g", "30"],
    "av1_cqp15_g30": ["-c:v", "av1_vulkan", "-rc_mode", "cqp", "-qp", "15", "-g", "30"],
}


def run(command, timeout=120):
    done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if done.returncode:
        raise RuntimeError(f"command failed ({done.returncode}): {command[:3]}: {done.stderr[-600:]}")
    return done


def raw_input(path):
    return ["-f", "rawvideo", "-pix_fmt", "nv12", "-video_size", SIZE,
            "-framerate", FPS, "-i", str(path)]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "driver": run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                       "--format=csv,noheader"]).stdout.strip(),
        "fixture": f"testsrc2 {SIZE}/{FPS}, {FRAMES} frames, one shared NV12 raw source",
        "results": {},
        "temporary_source_and_bitstreams_retained": False,
    }
    with tempfile.TemporaryDirectory(prefix="p16-av1-quality-") as folder:
        work = Path(folder)
        source = work / "source.nv12"
        run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"testsrc2=size={SIZE}:rate={FPS}",
             "-frames:v", str(FRAMES), "-pix_fmt", "nv12", "-f", "rawvideo",
             str(source)])
        expected = FRAMES * 1280 * 720 * 3 // 2
        if source.stat().st_size != expected:
            raise RuntimeError("source raw frame count mismatch")
        result["source_sha256"] = sha256(source)
        result["ffmpeg_sha256"] = sha256(Path("/usr/bin/ffmpeg"))
        result["aomdec_sha256"] = sha256(Path("/usr/bin/aomdec"))
        for name, options in CASES.items():
            video = work / f"{name}.mkv"
            decoded = work / f"{name}.nv12"
            stats = work / f"{name}.psnr"
            vulkan = name != "x264_crf18"
            command = ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error"]
            if vulkan:
                command += ["-init_hw_device", "vulkan=vk:0", "-filter_hw_device", "vk"]
            command += raw_input(source)
            if vulkan:
                command += ["-vf", "hwupload"]
            command += ["-frames:v", str(FRAMES), *options, "-y", str(video)]
            run(command)
            run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                 "-i", str(video), "-fps_mode", "passthrough", "-pix_fmt", "nv12",
                 "-f", "rawvideo", str(decoded)])
            if decoded.stat().st_size != expected:
                raise RuntimeError(f"decoded raw frame count mismatch: {name}")
            quality = run(["/usr/bin/ffmpeg", "-hide_banner", *raw_input(decoded),
                           *raw_input(source), "-filter_complex",
                           f"[0:v][1:v]psnr=stats_file={stats}:shortest=1",
                           "-frames:v", str(FRAMES), "-f", "null", "-"], timeout=120)
            values = [float(match.group(1)) for line in stats.read_text().splitlines()
                      if (match := re.search(r"psnr_avg:([0-9.]+)", line))]
            average = re.search(r"average:([0-9.]+)", quality.stderr)
            if len(values) != FRAMES or not average:
                raise RuntimeError(f"quality frame count mismatch: {name}: "
                                   f"{len(values)} values, average={average}")
            result["results"][name] = {
                "options": options,
                "encoded_bytes": video.stat().st_size,
                "encoded_sha256": sha256(video),
                "psnr_average_db": float(average.group(1)),
                "psnr_min_frame_db": round(min(values), 2),
                "psnr_min_frame_number": values.index(min(values)) + 1,
                "psnr_frames_below_30_db": sum(value < 30 for value in values),
                "psnr_frame_db": {str(i + 1): round(values[i], 2) for i in
                                  (0, 9, 29, 30, 59, 60, 89, 90, 119)},
                "psnr_frame_count": len(values),
            }
            if name.startswith("av1_"):
                ivf = work / f"{name}.ivf"
                davraw = work / f"{name}.dav1d.i420"
                aomraw = work / f"{name}.aom.i420"
                run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                     "-i", str(video), "-c:v", "copy", "-f", "ivf", str(ivf)])
                run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                     "-c:v", "libdav1d", "-i", str(ivf), "-fps_mode", "passthrough",
                     "-pix_fmt", "yuv420p", "-f", "rawvideo", str(davraw)])
                run(["/usr/bin/aomdec", "--i420", "--rawvideo", "-o",
                     str(aomraw), str(ivf)])
                if davraw.stat().st_size != expected or aomraw.stat().st_size != expected:
                    raise RuntimeError(f"cross-decoder frame count mismatch: {name}")
                result["results"][name]["cross_decoder"] = {
                    "dav1d_raw_sha256": sha256(davraw),
                    "libaom_raw_sha256": sha256(aomraw),
                    "pixel_equal": sha256(davraw) == sha256(aomraw),
                    "frames": FRAMES,
                }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({name: {"bytes": data["encoded_bytes"],
                             "psnr_db": data["psnr_average_db"]}
                      for name, data in result["results"].items()}))


if __name__ == "__main__":
    main()
