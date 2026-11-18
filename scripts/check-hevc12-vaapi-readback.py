#!/usr/bin/env python3
"""Compare 12-bit HEVC VA-API hwdownload pixels with software on the N1X."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, *, timeout=30, env=None):
    return subprocess.run(command, capture_output=True, text=True, check=True,
                          timeout=timeout, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x265-12", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    with tempfile.TemporaryDirectory(prefix="p16-hevc12-vaapi-readback-") as folder:
        work = Path(folder)
        raw = work / "source.yuv"
        bitstream = work / "clip.hevc"
        software = work / "software.p012"
        hardware = work / "hardware.p012"
        run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
             "-frames:v", "30", "-pix_fmt", "yuv420p12le",
             "-f", "rawvideo", "-y", str(raw)])
        run([str(args.x265_12), "--input", str(raw), "--input-res", "320x180",
             "--fps", "10", "--input-depth", "12", "--input-csp", "i420",
             "--frames", "30", "--preset", "ultrafast", "--crf", "22",
             "--output", str(bitstream)])
        stream = json.loads(run([
            "/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,profile,pix_fmt,width,height",
            "-of", "json", str(bitstream)]).stdout)["streams"][0]
        if (stream["codec_name"], stream["profile"], stream["pix_fmt"],
            stream["width"], stream["height"]) != (
                "hevc", "Rext", "yuv420p12le", 320, 180):
            raise RuntimeError("not a 12-bit HEVC RExt fixture: " + str(stream))
        sw = run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "verbose",
                  "-i", str(bitstream), "-frames:v", "30", "-pix_fmt",
                  "p012le", "-f", "rawvideo", "-y", str(software)])
        env = {**os.environ, "LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"}
        va = run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "verbose",
                  "-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128",
                  "-hwaccel_output_format", "vaapi", "-threads", "1",
                  "-i", str(bitstream), "-frames:v", "30", "-vf",
                  "hwdownload,format=p012le", "-f", "rawvideo", "-y",
                  str(hardware)], timeout=20, env=env)
        expected_bytes = 30 * 320 * 180 * 3
        sw_bytes, va_bytes = software.read_bytes(), hardware.read_bytes()
        backend_logged = "VA-API NVDEC driver [direct backend]" in va.stderr
        vaapi_surface_logged = "pixfmt:vaapi" in va.stderr
        zero_decode_errors = "0 decode errors" in sw.stderr and "0 decode errors" in va.stderr
        result = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
            "driver": run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                           "--format=csv,noheader"]).stdout.strip(),
            "libva_package": run(["/usr/bin/pacman", "-Q",
                                  "libva-nvidia-driver"]).stdout.strip(),
            "ffmpeg_package": run(["/usr/bin/pacman", "-Q", "ffmpeg"]).stdout.strip(),
            "x265_12_sha256": sha256(args.x265_12),
            "ffmpeg_sha256": sha256(Path("/usr/bin/ffmpeg")),
            "fixture": stream,
            "fixture_sha256": sha256(bitstream),
            "output_pixel_format": "p012le",
            "frames": 30,
            "expected_output_bytes": expected_bytes,
            "software_output_bytes": len(sw_bytes),
            "vaapi_output_bytes": len(va_bytes),
            "software_sha256": sha256(software),
            "vaapi_sha256": sha256(hardware),
            "pixels_equal": sw_bytes == va_bytes,
            "nvidia_vaapi_direct_backend_logged": backend_logged,
            "vaapi_surface_logged": vaapi_surface_logged,
            "zero_decode_errors_logged": zero_decode_errors,
            "decoder_threads": 1,
            "camera_or_fixture_pixels_retained": False,
        }
        result["pass"] = (len(sw_bytes) == len(va_bytes) == expected_bytes and
                          result["pixels_equal"] and backend_logged and
                          vaapi_surface_logged and zero_decode_errors)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "pixels_equal": result["pixels_equal"],
                      "frames": result["frames"],
                      "vaapi_output_bytes": result["vaapi_output_bytes"]}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
