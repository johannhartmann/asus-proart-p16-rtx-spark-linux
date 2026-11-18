#!/usr/bin/env python3
"""Compare a bounded N1X libplacebo Vulkan upscale with CPU bicubic."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


WIDTH, HEIGHT = 1280, 720
LOW_WIDTH, LOW_HEIGHT = 640, 360
FRAME_BYTES = WIDTH * HEIGHT * 3 // 2


def run(command, *, timeout=120):
    started = time.monotonic()
    done = subprocess.run(command, capture_output=True, text=True,
                          timeout=timeout, check=False)
    if done.returncode:
        raise RuntimeError(f"command failed ({done.returncode}): {command!r}\n"
                           + done.stderr[-3000:])
    return done.stderr, round(time.monotonic() - started, 3)


def digest(path):
    hash_ = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_.update(chunk)
    return hash_.hexdigest()


def frame_samples(path, frames):
    with path.open("rb") as stream:
        hashes = []
        for index in (0, frames // 2, frames - 1):
            stream.seek(index * FRAME_BYTES)
            hashes.append(hashlib.sha256(stream.read(FRAME_BYTES)).hexdigest())
    return hashes


def metric(ffmpeg, output, reference, filter_name, frames):
    input_args = ["-f", "rawvideo", "-pixel_format", "nv12",
                  "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", "30"]
    stderr, _ = run([str(ffmpeg), "-hide_banner", "-loglevel", "info",
                     *input_args, "-i", str(output), *input_args, "-i",
                     str(reference), "-filter_complex", filter_name,
                     "-frames:v", str(frames), "-f", "null", "-"])
    if filter_name == "psnr":
        match = re.search(r"PSNR y:([\d.]+) u:([\d.]+) v:([\d.]+) "
                          r"average:([\d.]+)", stderr)
        if not match:
            raise RuntimeError("PSNR summary missing: " + stderr[-1000:])
        values = list(map(float, match.groups()))
        return dict(zip(("y", "u", "v", "average"), values))
    match = re.search(r"All:([\d.]+) \(([\d.]+)\)", stderr)
    if not match:
        raise RuntimeError("SSIM summary missing: " + stderr[-1000:])
    return {"all": float(match.group(1)), "db": float(match.group(2))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--color-tagged", action="store_true",
                        help="tag the raw input and output as limited-range BT.709")
    parser.add_argument("--upscaler", choices=("ewa_lanczos", "ewa_lanczossharp",
                                               "lanczos", "spline36", "spline64",
                                               "bilinear"),
                        default="ewa_lanczos")
    parser.add_argument("--minimum-libplacebo-api", type=int, default=365,
                        help="minimum API version accepted for this candidate")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 10 <= args.frames <= 300:
        parser.error("frames must be 10–300")
    if args.output.exists():
        parser.error("choose a new output path")
    ffmpeg = args.ffmpeg.resolve(strict=True)
    frames = args.frames
    with tempfile.TemporaryDirectory(prefix="p16-upscale-quality-") as folder:
        work = Path(folder)
        reference = work / "reference.nv12"
        low = work / "low.nv12"
        cpu = work / "cpu-bicubic.nv12"
        gpu = work / "gpu-libplacebo.nv12"
        raw = ["-f", "rawvideo", "-pixel_format", "nv12",
               "-framerate", "30"]
        run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f",
             "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-frames:v",
             str(frames), "-pix_fmt", "nv12", "-f", "rawvideo", "-y",
             str(reference)])
        run([str(ffmpeg), "-hide_banner", "-loglevel", "error", *raw,
             "-video_size", f"{WIDTH}x{HEIGHT}", "-i", str(reference),
             "-vf", "scale=640:360:flags=lanczos", "-frames:v", str(frames),
             "-pix_fmt", "nv12", "-f", "rawvideo", "-y", str(low)])
        _, cpu_seconds = run([str(ffmpeg), "-hide_banner", "-loglevel", "error",
                              *raw, "-video_size", f"{LOW_WIDTH}x{LOW_HEIGHT}",
                              "-i", str(low), "-vf", "scale=1280:720:flags=bicubic",
                              "-frames:v", str(frames), "-pix_fmt", "nv12",
                              "-f", "rawvideo", "-y", str(cpu)])
        gpu_filter = ("format=nv12,hwupload,libplacebo=w=1280:h=720:"
                      f"upscaler={args.upscaler},hwdownload,format=nv12")
        if args.color_tagged:
            gpu_filter = ("setparams=range=tv:color_primaries=bt709:"
                          "color_trc=bt709:colorspace=bt709," +
                          "format=nv12,hwupload,libplacebo=w=1280:h=720:"
                          f"upscaler={args.upscaler}:range=limited:colorspace=bt709:"
                          "color_primaries=bt709:color_trc=bt709,hwdownload,"
                          "format=nv12")
        gpu_stderr, gpu_seconds = run([
            str(ffmpeg), "-hide_banner", "-loglevel", "verbose",
            "-init_hw_device", "vulkan=vk:0", "-filter_hw_device", "vk",
            *raw, "-video_size", f"{LOW_WIDTH}x{LOW_HEIGHT}", "-i", str(low),
            "-vf", gpu_filter,
            "-frames:v", str(frames), "-pix_fmt", "nv12", "-f", "rawvideo",
            "-y", str(gpu)])
        expected = frames * FRAME_BYTES
        sizes = {name: path.stat().st_size for name, path in
                 (("reference", reference), ("cpu", cpu), ("gpu", gpu))}
        if any(size != expected for size in sizes.values()):
            raise RuntimeError(f"wrong output sizes: {sizes}, expected {expected}")
        gpu_frames = frame_samples(gpu, frames)
        cpu_frames = frame_samples(cpu, frames)
        api_match = re.search(r"Initialized libplacebo .*\(API v(\d+)\)",
                              gpu_stderr)
        result = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
            "nvidia_driver": subprocess.check_output([
                "/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                "--format=csv,noheader"], text=True).strip(),
            "ffmpeg_path": str(ffmpeg), "ffmpeg_sha256": digest(ffmpeg),
            "frames": frames, "source": "testsrc2 1280x720/30 NV12",
            "downsample": "software Lanczos 640x360",
            "control": "software bicubic 1280x720",
            "candidate": f"Vulkan/libplacebo {args.upscaler} 1280x720",
            "gpu_filter": gpu_filter,
            "explicit_bt709_limited_tags": args.color_tagged,
            "expected_bytes_per_full_resolution_output": expected,
            "output_bytes": sizes,
            "gpu_device_logged": "NVIDIA RTX Spark N1X" in gpu_stderr,
            "libplacebo_api_logged": int(api_match.group(1)) if api_match else None,
            "minimum_libplacebo_api_required": args.minimum_libplacebo_api,
            "gpu_sample_frame_hashes": gpu_frames,
            "cpu_sample_frame_hashes": cpu_frames,
            "gpu_sample_frames_distinct": len(set(gpu_frames)) == 3,
            "cpu_sample_frames_distinct": len(set(cpu_frames)) == 3,
            "gpu_output_sha256": digest(gpu),
            "cpu_output_sha256": digest(cpu),
            "gpu_psnr_db": metric(ffmpeg, gpu, reference, "psnr", frames),
            "cpu_psnr_db": metric(ffmpeg, cpu, reference, "psnr", frames),
            "gpu_ssim": metric(ffmpeg, gpu, reference, "ssim", frames),
            "cpu_ssim": metric(ffmpeg, cpu, reference, "ssim", frames),
            "gpu_wall_seconds_including_startup_and_file_io": gpu_seconds,
            "cpu_wall_seconds_including_startup_and_file_io": cpu_seconds,
            "temporary_pixels_retained": False,
        }
        result["functional_pass"] = (
            result["gpu_device_logged"] and
            result["libplacebo_api_logged"] is not None and
            result["libplacebo_api_logged"] >= args.minimum_libplacebo_api and
            result["gpu_sample_frames_distinct"] and
            all(math.isfinite(value) for value in result["gpu_psnr_db"].values()) and
            0 < result["gpu_ssim"]["all"] <= 1)
        result["quality_vs_bicubic_on_this_fixture"] = (
            result["gpu_psnr_db"]["y"] >= result["cpu_psnr_db"]["y"] and
            result["gpu_ssim"]["all"] >= result["cpu_ssim"]["all"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"functional_pass": result["functional_pass"],
                      "quality_vs_bicubic_on_this_fixture":
                      result["quality_vs_bicubic_on_this_fixture"],
                      "frames": frames,
                      "gpu_psnr_y_db": result["gpu_psnr_db"]["y"],
                      "cpu_psnr_y_db": result["cpu_psnr_db"]["y"],
                      "gpu_ssim": result["gpu_ssim"]["all"],
                      "cpu_ssim": result["cpu_ssim"]["all"]}))
    return 0 if result["functional_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
