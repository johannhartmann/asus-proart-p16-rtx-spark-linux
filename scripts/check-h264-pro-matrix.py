#!/usr/bin/env python3
"""Qualify H.264 High 4:2:2 pixels/playback and record High 4:4:4 skips."""

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


CASES = (("422-8", "yuv422p", "High 4:2:2", "nv16", 8, True),
         ("422-10", "yuv422p10le", "High 4:2:2", "p210le", 10, True),
         ("444-8", "yuv444p", "High 4:4:4 Predictive", None, 8, False),
         ("444-10", "yuv444p10le", "High 4:4:4 Predictive", None, 10, False))
FRAMES = 30


def run(command, *, env=None, timeout=30):
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              check=False, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as error:
        def decode(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        return subprocess.CompletedProcess(command, 124, decode(error.stdout),
                                           decode(error.stderr))


def required(command, **kwargs):
    result = run(command, **kwargs)
    if result.returncode:
        raise RuntimeError(f"exit {result.returncode}: {command!r}\n{result.stderr[-1200:]}")
    return result


def digest(path):
    hash_ = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            hash_.update(block)
    return hash_.hexdigest()


def save_log(directory, label, command, result, work):
    content = ("$ " + " ".join(command) + "\nexit_code=" + str(result.returncode)
               + "\n\nstdout:\n" + result.stdout + "\nstderr:\n" + result.stderr)
    content = content.replace(str(work), "$WORKDIR").replace(str(Path.home()), "$HOME")
    content = re.sub(r"Device UUID:\s*[0-9A-Fa-f:]+", "Device UUID: [redacted]", content)
    (directory / (label + ".log")).write_text(
        "\n".join(line.rstrip() for line in content.replace("\r", "\n").splitlines()) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=Path, default=Path("/usr/bin/ffmpeg-n1x"))
    parser.add_argument("--ffplay", type=Path, default=Path("/usr/bin/ffplay-n1x"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("choose a new output directory")
    monitors = json.loads(required(["hyprctl", "monitors", "-j"]).stdout)
    if not monitors or not all(m.get("dpmsStatus") for m in monitors):
        parser.error("timed FFplay playback requires all active displays on")
    ffmpeg, ffplay = args.ffmpeg.resolve(strict=True), args.ffplay.resolve(strict=True)
    args.output_dir.mkdir(parents=True)
    results = {}
    with tempfile.TemporaryDirectory(prefix="n1x-h264-pro-") as temporary:
        work = Path(temporary)
        for name, fmt, profile, surface, depth, supported in CASES:
            fixture = work / (name + ".mkv")
            encode = ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "verbose",
                      "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                      "-frames:v", str(FRAMES), "-pix_fmt", fmt, "-c:v", "libx264",
                      "-preset", "ultrafast", "-x264-params", "log-level=error",
                      "-y", str(fixture)]
            save_log(args.output_dir, name + "-encode", encode,
                     required(encode), work)
            probe = json.loads(required(["/usr/bin/ffprobe", "-v", "error",
                                         "-select_streams", "v:0", "-count_frames",
                                         "-show_entries",
                                         "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames",
                                         "-of", "json", str(fixture)]).stdout)["streams"][0]
            if tuple(probe.get(key) for key in
                     ("codec_name", "profile", "pix_fmt", "width", "height",
                      "nb_read_frames")) != ("h264", profile, fmt, 320, 180, "30"):
                raise RuntimeError(f"wrong fixture {name}: {probe}")
            swfile, hwfile = work / (name + "-sw.raw"), work / (name + "-cuvid.raw")
            software = ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "verbose",
                        "-i", str(fixture), "-frames:v", str(FRAMES),
                        "-pix_fmt", fmt, "-f", "rawvideo", "-y", str(swfile)]
            save_log(args.output_dir, name + "-software", software,
                     required(software), work)
            hardware = [str(ffmpeg), "-hide_banner", "-loglevel", "verbose",
                        "-c:v", "h264_cuvid", "-i", str(fixture), "-frames:v",
                        str(FRAMES), "-pix_fmt", fmt, "-f", "rawvideo", "-y",
                        str(hwfile)]
            hw = run(hardware)
            save_log(args.output_dir, name + "-cuvid", hardware, hw, work)
            vaapi_command = ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel",
                             "verbose", "-hwaccel", "vaapi", "-hwaccel_device",
                             "/dev/dri/renderD128", "-hwaccel_output_format",
                             "vaapi", "-i", str(fixture), "-frames:v", "2",
                             "-f", "null", "-"]
            vaapi = run(vaapi_command, env={**os.environ,
                        "LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"})
            save_log(args.output_dir, name + "-vaapi-control", vaapi_command,
                     vaapi, work)
            expected_bytes = 320 * 180 * FRAMES * (4 if "422" in name else 6) * (2 if depth == 10 else 1) // 2
            checks = {"software_output_size": swfile.stat().st_size == expected_bytes,
                      "cuvid_capability_reported": "CUVID capabilities for h264_cuvid" in hw.stderr,
                      "vaapi_software_fallback_control": vaapi.returncode == 0 and
                             "VA-API NVDEC driver [direct backend]" in vaapi.stderr and
                             f"pixfmt:{fmt}" in vaapi.stderr and
                             "pixfmt:vaapi" not in vaapi.stderr}
            if supported:
                checks.update({"cuvid_exit": hw.returncode == 0,
                               "cuvid_output_size": hwfile.exists() and
                                                    hwfile.stat().st_size == expected_bytes,
                               "cuvid_pixels_equal": hwfile.exists() and
                                                     digest(hwfile) == digest(swfile),
                               "cuvid_surface": f"Formats: Original: {surface} | HW: {surface} | SW: {surface}" in hw.stderr,
                               "cuvid_frames": bool(re.search(r"frame=\s*30\b", hw.stderr))})
                play = [str(ffplay), "-hide_banner", "-autoexit", "-loglevel",
                        "verbose", "-enable_vulkan", "-an", "-vcodec",
                        "h264_cuvid", str(fixture)]
                shown = run(play, timeout=18, env={**os.environ,
                            "SDL_VIDEODRIVER": "wayland"})
                save_log(args.output_dir, name + "-ffplay", play, shown, work)
                clock = [float(value) for value in re.findall(
                    r"(\d+\.\d+) M-V:", shown.stdout + shown.stderr)]
                checks.update({"ffplay_eof": shown.returncode == 0 and
                                              bool(clock) and max(clock) >= 2.7,
                               "ffplay_vulkan_surface": "Initialized libplacebo" in shown.stderr and
                                  "Device 0 selected: NVIDIA RTX Spark N1X" in shown.stderr and
                                  f"pixfmt:{surface}" in shown.stderr and
                                  "SDL_PIXELFORMAT_IYUV" not in shown.stderr})
            else:
                checks.update({"cuvid_rejects_profile": hw.returncode != 0 and
                               "not supported with this chroma format" in hw.stderr and
                               f"{depth} bit: supported: 0" in hw.stderr,
                               "no_output_frames": not hwfile.exists() or
                                                   hwfile.stat().st_size == 0})
            results[name] = {"status": "pass" if all(checks.values()) else "fail",
                             "expected_hardware_support": supported,
                             "fixture": probe, "fixture_sha256": digest(fixture),
                             "software_sha256": digest(swfile),
                             "cuvid_sha256": digest(hwfile) if hwfile.exists() else None,
                             "expected_output_bytes": expected_bytes,
                             "checks": checks}
    report = {"captured_at": datetime.now(timezone.utc).isoformat(),
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
              "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
              "nvidia_driver": required(["/usr/bin/nvidia-smi",
                                         "--query-gpu=driver_version",
                                         "--format=csv,noheader"]).stdout.strip(),
              "ffmpeg": str(ffmpeg).replace(str(Path.home()), "$HOME"),
              "ffmpeg_sha256": digest(ffmpeg),
              "ffplay": str(ffplay).replace(str(Path.home()), "$HOME"),
              "ffplay_sha256": digest(ffplay),
              "cases": results, "status": "pass" if all(
                  item["status"] == "pass" for item in results.values()) else "fail",
              "temporary_pixels_retained": False,
              "limit": "H.264 4:4:4 CUVID is rejected on this 615 N1X stack; VA-API does not advertise High 4:2:2/4:4:4. No post-resume or display color measurement."}
    (args.output_dir / "h264-pro-matrix.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": {
        name: item["checks"] for name, item in results.items()}}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
