#!/usr/bin/env python3
"""Compare 30 HEVC RExt 4:4:4 8-bit VA-API frames against software decode."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


WIDTH, HEIGHT, FRAMES = 320, 180, 30
EXPECTED_BYTES = WIDTH * HEIGHT * FRAMES * 3


def run(command, *, env=None, timeout=30):
    result = subprocess.run(command, capture_output=True, text=True,
                            env=env, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"exit {result.returncode}: {command!r}\n{result.stderr[-1800:]}")
    return result


def digest(path):
    hash_ = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            hash_.update(block)
    return hash_.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x265", type=Path, default=Path("/usr/bin/x265"))
    parser.add_argument("--ffmpeg", type=Path, default=Path("/usr/bin/ffmpeg"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    x265, ffmpeg = args.x265.resolve(strict=True), args.ffmpeg.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="p16-hevc4448-") as folder:
        work = Path(folder)
        source, clip = work / "source.yuv", work / "clip.hevc"
        software, hardware = work / "software.yuv", work / "vaapi.yuv"
        source_command = [str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                          "testsrc2=size=320x180:rate=10", "-frames:v", str(FRAMES),
                          "-pix_fmt", "yuv444p", "-f", "rawvideo", "-y", str(source)]
        encode_command = [str(x265), "--input", str(source), "--input-res", "320x180",
                          "--fps", "10", "--input-depth", "8", "--input-csp", "i444",
                          "--frames", str(FRAMES), "--preset", "ultrafast", "--crf", "22",
                          "--output", str(clip)]
        source_result = run(source_command)
        encode_result = run(encode_command)
        probe = json.loads(run(["/usr/bin/ffprobe", "-v", "error",
                                "-select_streams", "v:0", "-count_frames",
                                "-show_entries",
                                "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames",
                                "-of", "json", str(clip)]).stdout)["streams"][0]
        if tuple(probe.get(key) for key in
                 ("codec_name", "profile", "pix_fmt", "width", "height",
                  "nb_read_frames")) != ("hevc", "Rext", "yuv444p", WIDTH,
                                        HEIGHT, str(FRAMES)):
            raise RuntimeError(f"wrong HEVC fixture: {probe}")
        software_command = [str(ffmpeg), "-hide_banner", "-loglevel", "verbose",
                            "-i", str(clip), "-frames:v", str(FRAMES), "-pix_fmt",
                            "yuv444p", "-f", "rawvideo", "-y", str(software)]
        vaapi_command = [str(ffmpeg), "-hide_banner", "-loglevel", "verbose",
                         "-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128",
                         "-hwaccel_output_format", "vaapi", "-threads", "1", "-i",
                         str(clip), "-frames:v", str(FRAMES), "-vf",
                         "hwdownload,format=yuv444p", "-f", "rawvideo", "-y",
                         str(hardware)]
        sw = run(software_command)
        va = run(vaapi_command, env={**os.environ,
                 "LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"})
        for label, command, result in (("source", source_command, source_result),
                                       ("encode", encode_command, encode_result),
                                       ("software", software_command, sw),
                                       ("vaapi", vaapi_command, va)):
            log = ("$ " + " ".join(command) + "\nexit_code=" + str(result.returncode)
                   + "\n\nstdout:\n" + result.stdout + "\nstderr:\n" + result.stderr)
            args.output.with_name(args.output.stem + f"-{label}.log").write_text(
                "\n".join(line.rstrip() for line in
                          log.replace(str(work), "$WORKDIR").replace("\r", "\n").splitlines())
                + "\n")
        software_hash, hardware_hash = digest(software), digest(hardware)
        checks = {
            "fixture_profile": True,
            "software_bytes": software.stat().st_size == EXPECTED_BYTES,
            "vaapi_bytes": hardware.stat().st_size == EXPECTED_BYTES,
            "pixels_equal": software_hash == hardware_hash,
            "vaapi_direct_backend": "VA-API NVDEC driver [direct backend]" in va.stderr,
            "vaapi_surface": "pixfmt:vaapi" in va.stderr,
            "software_frames_logged": bool(re.search(r"frame=\s*30\b", sw.stderr)),
            "vaapi_frames_logged": bool(re.search(r"frame=\s*30\b", va.stderr)),
        }
        report = {"captured_at": datetime.now(timezone.utc).isoformat(),
                  "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                  "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
                  "nvidia_driver": run(["/usr/bin/nvidia-smi",
                                        "--query-gpu=driver_version",
                                        "--format=csv,noheader"]).stdout.strip(),
                  "libva_package": run(["/usr/bin/pacman", "-Q",
                                        "libva-nvidia-driver"]).stdout.strip(),
                  "ffmpeg_package": run(["/usr/bin/pacman", "-Q", "ffmpeg"]).stdout.strip(),
                  "ffmpeg_path": str(ffmpeg), "ffmpeg_sha256": digest(ffmpeg),
                  "x265_path": str(x265), "x265_sha256": digest(x265),
                  "fixture": probe, "fixture_sha256": digest(clip),
                  "expected_output_bytes": EXPECTED_BYTES,
                  "software_sha256": software_hash, "vaapi_sha256": hardware_hash,
                  "checks": checks, "pass": all(checks.values()),
                  "temporary_pixels_retained": False}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "checks": checks}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
