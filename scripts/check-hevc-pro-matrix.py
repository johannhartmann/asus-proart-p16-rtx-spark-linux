#!/usr/bin/env python3
"""Qualify HEVC 4:4:4 and 4:2:2 decode paths on the P16 N1X."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


CASES = (("444", 8), ("444", 10), ("422", 8), ("422", 10), ("422", 12))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, label, evidence, work, *, env=None, timeout=25):
    result = subprocess.run(command, capture_output=True, text=True, check=False,
                            timeout=timeout, env={**os.environ, **(env or {})})
    content = "$ " + " ".join(map(str, command)) + "\nexit_code=" + str(
        result.returncode) + "\n\nstdout:\n" + result.stdout + "\nstderr:\n" + result.stderr
    content = content.replace(str(Path.home()), "$HOME").replace(str(work), "$WORKDIR")
    content = "\n".join(line.rstrip() for line in content.replace("\r", "\n").splitlines()) + "\n"
    (evidence / f"{label}.log").write_text(content)
    return result


def hashes(text):
    return re.findall(r"^0,\s*\d+,\s*\d+,\s*\d+,\s*\d+,\s*([0-9a-f]{32})$",
                      text, re.MULTILINE)


def check_case(chroma, depth, args, work):
    label = f"hevc-{chroma}-{depth}bit"
    pixel = f"yuv{chroma}p" + (f"{depth}le" if depth > 8 else "")
    raw = work / "source.yuv"
    video = work / "stream.hevc"
    encoder = {8: args.x265_8, 10: args.x265_10, 12: args.x265_12}[depth]
    evidence = args.output_dir
    source = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                  "-i", "testsrc2=size=320x180:rate=10", "-frames:v", "30",
                  "-pix_fmt", pixel, "-f", "rawvideo", "-y", str(raw)],
                 f"{label}-source", evidence, work)
    if source.returncode:
        raise RuntimeError(f"{label}: fixture source failed")
    encoded = run([encoder, "--input", str(raw), "--input-res", "320x180",
                   "--fps", "10", "--input-depth", str(depth), "--input-csp",
                   "i" + chroma, "--frames", "30", "--preset", "ultrafast",
                   "--crf", "22", "--output", str(video)],
                  f"{label}-x265", evidence, work)
    if encoded.returncode:
        raise RuntimeError(f"{label}: x265 fixture failed")
    probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-count_frames", "-show_entries",
                 "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames",
                 "-of", "json", str(video)], f"{label}-probe", evidence, work)
    if probe.returncode:
        raise RuntimeError(f"{label}: ffprobe failed")
    stream = json.loads(probe.stdout)["streams"][0]
    if (stream.get("codec_name"), stream.get("profile"), stream.get("pix_fmt"),
        stream.get("width"), stream.get("height"), stream.get("nb_read_frames")) != (
            "hevc", "Rext", pixel, 320, 180, "30"):
        raise RuntimeError(f"{label}: wrong fixture {stream}")

    software = run(["ffmpeg", "-hide_banner", "-loglevel", "verbose",
                    "-i", str(video), "-frames:v", "30", "-pix_fmt", pixel,
                    "-f", "framemd5", "-"], f"{label}-software", evidence, work)
    cuvid = run([args.ffmpeg_cuvid, "-hide_banner", "-loglevel", "verbose",
                 "-c:v", "hevc_cuvid", "-i", str(video), "-frames:v", "30",
                 "-pix_fmt", pixel, "-f", "framemd5", "-"],
                f"{label}-cuvid", evidence, work)
    reference = hashes(software.stdout)
    direct = hashes(cuvid.stdout)
    if (software.returncode or cuvid.returncode or len(reference) != 30 or
            direct != reference or "hevc_cuvid" not in cuvid.stderr):
        raise RuntimeError(f"{label}: CUVID pixel comparison failed")

    vaapi = run(["ffmpeg", "-hide_banner", "-loglevel", "verbose",
                 "-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128",
                 "-hwaccel_output_format", "vaapi", "-i", str(video),
                 "-frames:v", "30", "-f", "null", "-"],
                f"{label}-vaapi", evidence, work,
                env={"LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"})
    vaapi_hardware = (vaapi.returncode == 0 and
                      "VA-API NVDEC driver [direct backend]" in vaapi.stderr and
                      "pixfmt:vaapi" in vaapi.stderr and
                      "Failed setup for format vaapi" not in vaapi.stderr and
                      re.search(r"frame=\s*30\b", vaapi.stderr) is not None)
    vaapi_fallback = "Failed setup for format vaapi" in vaapi.stderr
    if (chroma == "444" and not vaapi_hardware) or (
            chroma == "422" and not vaapi_fallback):
        raise RuntimeError(f"{label}: unexpected VA-API result")

    player = run([args.player, str(video), "--no-config", "--no-audio",
                  "--frames=30", "--force-window=yes", "--autofit=640x360",
                  "--hwdec=hevc-vulkan"], f"{label}-player", evidence, work,
                 timeout=20)
    vulkan_hardware = ("Using hardware decoding (vulkan)." in player.stdout and
                       re.search(r"VO: \[gpu-next\].*vulkan\[([^]]+)\]",
                                 player.stdout) is not None)
    surface_match = re.search(r"VO: \[gpu-next\].*?(vulkan\[[^]]+\]|yuv\w+)",
                              player.stdout)
    surface = surface_match.group(1) if surface_match else None
    expected_surface = {8: "vulkan[nv24]", 10: "vulkan[p410]"}.get(depth)
    if (player.returncode or "Exiting... (End of file)" not in player.stdout or
            (chroma == "444" and (not vulkan_hardware or surface != expected_surface)) or
            (chroma == "422" and vulkan_hardware)):
        raise RuntimeError(f"{label}: unexpected application decode path")

    ffplay_hardware = None
    ffplay_texture = None
    if chroma == "422" and args.ffplay_cuvid:
        ffplay = run([args.ffplay_cuvid, "-hide_banner", "-autoexit", "-an",
                      "-loglevel", "verbose", "-vcodec", "hevc_cuvid",
                      "-framerate", "10", "-f", "hevc", str(video)],
                     f"{label}-ffplay-cuvid", evidence, work,
                     env={"SDL_VIDEODRIVER": "wayland"}, timeout=20)
        texture = re.search(r"Created \d+x\d+ texture with (SDL_PIXELFORMAT_\w+)",
                            ffplay.stderr)
        ffplay_hardware = (ffplay.returncode == 0 and
                           "CUVID capabilities for hevc_cuvid" in ffplay.stderr and
                           f"{depth} bit: supported: 1" in ffplay.stderr and
                           "Formats: Original:" in ffplay.stderr and
                           texture is not None)
        ffplay_texture = texture.group(1) if texture else None
        if not ffplay_hardware:
            raise RuntimeError(f"{label}: FFplay did not use CUVID through EOF")

    return {"status": "observed", "fixture": stream,
            "fixture_sha256": sha256(video), "software_cuvid_pixel_match": True,
            "frame_hashes_sha256": hashlib.sha256("\n".join(reference).encode()).hexdigest(),
            "vaapi_hardware": vaapi_hardware, "vaapi_software_fallback": vaapi_fallback,
            "player_vulkan_hardware": vulkan_hardware, "player_surface": surface,
            "mpv_hardware_decode": vulkan_hardware,
            "ffplay_cuvid_hardware_decode": ffplay_hardware,
            "ffplay_texture": ffplay_texture,
            "limits": "Raw HEVC fixture has no timestamps; playback pacing and audio sync are not qualified."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for depth in (8, 10, 12):
        parser.add_argument(f"--x265-{depth}", required=True)
    parser.add_argument("--ffmpeg-cuvid", required=True)
    parser.add_argument("--player", default="/usr/bin/p16-video-play")
    parser.add_argument("--ffplay-cuvid", help="isolated FFplay binary for 4:2:2 application test")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "machine": "ASUS ProArt P16 H7607BA",
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "driver": subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            text=True, timeout=10).strip(),
        "binaries_sha256": {
            "x265_8": sha256(args.x265_8), "x265_10": sha256(args.x265_10),
            "x265_12": sha256(args.x265_12),
            "ffmpeg_cuvid": sha256(args.ffmpeg_cuvid),
            "player": sha256(args.player),
            "ffplay_cuvid": sha256(args.ffplay_cuvid) if args.ffplay_cuvid else None},
        "cases": {},
    }
    failures = 0
    for chroma, depth in CASES:
        name = f"hevc_{chroma}_{depth}bit"
        try:
            with tempfile.TemporaryDirectory(prefix="n1x-hevc-pro-") as directory:
                report["cases"][name] = check_case(chroma, depth, args, Path(directory))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            report["cases"][name] = {"status": "fail", "reason": str(exc)}
            failures += 1
    (args.output_dir / "hevc-pro-matrix.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: case["status"] for name, case in report["cases"].items()},
                     indent=2))
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
