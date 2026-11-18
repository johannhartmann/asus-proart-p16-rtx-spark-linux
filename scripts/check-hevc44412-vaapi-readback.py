#!/usr/bin/env python3
"""Check whether NVIDIA VA-API preserves HEVC 12-bit 4:4:4 pixels."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


WIDTH, HEIGHT, FRAMES = 320, 180, 30


def run(command, *, timeout=30, env=None):
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout, env=env)
        return done.returncode, done.stderr, done.stdout, False
    except subprocess.TimeoutExpired as error:
        return None, (error.stderr or b"").decode(errors="replace"), "", True


def required(command, **kwargs):
    code, stderr, stdout, timed_out = run(command, **kwargs)
    if code != 0 or timed_out:
        raise RuntimeError(f"command failed ({code}, timeout={timed_out}): "
                           f"{command!r}\n{stderr[-2000:]}")
    return stderr, stdout


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_planes(a, b):
    plane_size = WIDTH * HEIGHT * FRAMES
    return [round(sum(abs(x-y) for x, y in zip(a[i*plane_size:(i+1)*plane_size],
                                                b[i*plane_size:(i+1)*plane_size])) / plane_size, 3)
            for i in range(3)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x265-12", required=True, type=Path)
    parser.add_argument("--ffmpeg", type=Path, default=Path("/usr/bin/ffmpeg"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    with tempfile.TemporaryDirectory(prefix="p16-hevc44412-vaapi-") as folder:
        work = Path(folder)
        source, bitstream = work / "source.yuv", work / "clip.hevc"
        required([str(args.ffmpeg), "-hide_banner", "-loglevel", "error",
                  "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                  "-frames:v", str(FRAMES), "-pix_fmt", "yuv444p12le",
                  "-f", "rawvideo", "-y", str(source)])
        required([str(args.x265_12), "--input", str(source), "--input-res", "320x180",
                  "--fps", "10", "--input-depth", "12", "--input-csp", "i444",
                  "--frames", str(FRAMES), "--preset", "ultrafast", "--crf", "22",
                  "--output", str(bitstream)])
        stream = json.loads(required(["/usr/bin/ffprobe", "-v", "error",
                                      "-select_streams", "v:0", "-show_entries",
                                      "stream=codec_name,profile,pix_fmt,width,height",
                                      "-of", "json", str(bitstream)])[1])["streams"][0]
        if (stream["codec_name"], stream["profile"], stream["pix_fmt"],
            stream["width"], stream["height"]) != (
                "hevc", "Rext", "yuv444p12le", WIDTH, HEIGHT):
            raise RuntimeError("fixture is not HEVC RExt 12-bit 4:4:4: " + str(stream))
        env = {**os.environ, "LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"}
        checks = {}
        for fmt, frames in (("yuv444p16le", FRAMES), ("yuv444p12le", 1),
                            ("p412le", 1), ("yuv444p", FRAMES)):
            sw_path, va_path = work / f"sw-{fmt}.raw", work / f"va-{fmt}.raw"
            if fmt in ("yuv444p16le", "yuv444p"):
                required([
                    str(args.ffmpeg), "-hide_banner", "-loglevel", "verbose",
                    "-i", str(bitstream), "-frames:v", str(frames), "-pix_fmt",
                    fmt, "-f", "rawvideo", "-y", str(sw_path)])
            va_code, va_stderr, _, timed_out = run([
                str(args.ffmpeg), "-hide_banner", "-loglevel", "verbose",
                "-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128",
                "-hwaccel_output_format", "vaapi", "-threads", "1", "-i",
                str(bitstream), "-frames:v", str(frames), "-vf",
                f"hwdownload,format={fmt}", "-f", "rawvideo", "-y",
                str(va_path)], timeout=25, env=env)
            sw_data = sw_path.read_bytes() if sw_path.exists() else None
            va_data = va_path.read_bytes() if va_path.exists() else None
            check = {
                "frames_requested": frames,
                "exit_code": va_code,
                "timed_out": timed_out,
                "vaapi_direct_backend_logged": "VA-API NVDEC driver [direct backend]" in va_stderr,
                "vaapi_surface_logged": "pixfmt:vaapi" in va_stderr,
                "vaapi_error": next((line.strip() for line in va_stderr.splitlines()
                                      if "Invalid output format" in line), None),
                "vaapi_output_bytes": len(va_data) if va_data is not None else None,
                "software_output_bytes": len(sw_data) if sw_data is not None else None,
                "vaapi_sha256": hashlib.sha256(va_data).hexdigest() if va_data else None,
                "software_sha256": hashlib.sha256(sw_data).hexdigest() if sw_data else None,
                "pixels_equal": (sw_data == va_data if va_code == 0 and sw_data is not None and
                                 va_data is not None else None),
            }
            if sw_data is not None and va_data is not None and len(sw_data) == len(va_data) == WIDTH * HEIGHT * FRAMES * 3:
                check["mean_absolute_error_8bit_by_plane_yuv"] = compare_planes(sw_data, va_data)
                check["first_8_y_bytes_software"] = list(sw_data[:8])
                check["first_8_y_bytes_vaapi"] = list(va_data[:8])
            checks[fmt] = check
        result = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
            "libva_package": required(["/usr/bin/pacman", "-Q", "libva-nvidia-driver"])[1].strip(),
            "ffmpeg_package": required(["/usr/bin/pacman", "-Q", "ffmpeg"])[1].strip(),
            "ffmpeg_path": str(args.ffmpeg),
            "ffmpeg_sha256": sha256(args.ffmpeg),
            "x265_12_sha256": sha256(args.x265_12),
            "fixture": stream,
            "fixture_sha256": sha256(bitstream),
            "checks": checks,
            "high_bit_depth_vaapi_readback_pass": (
                checks["yuv444p16le"]["exit_code"] == 0 and
                checks["yuv444p16le"]["vaapi_output_bytes"] == WIDTH * HEIGHT * FRAMES * 6 and
                checks["yuv444p16le"]["pixels_equal"] is True and
                checks["yuv444p16le"]["vaapi_direct_backend_logged"] and
                checks["yuv444p16le"]["vaapi_surface_logged"]),
            "camera_or_fixture_pixels_retained": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"high_bit_depth_vaapi_readback_pass": result["high_bit_depth_vaapi_readback_pass"],
                      "checks": {fmt: {"exit_code": val["exit_code"], "pixels_equal": val["pixels_equal"]}
                                 for fmt, val in checks.items()}}))
    return 0 if result["high_bit_depth_vaapi_readback_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
