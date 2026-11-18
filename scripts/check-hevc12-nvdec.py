#!/usr/bin/env python3
"""Generate 12-bit HEVC 4:2:0/4:4:4 and compare CUVID pixels with software."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, label, evidence, *, env=None, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, check=False,
                            timeout=timeout, env={**os.environ, **(env or {})})
    content = (
        "$ " + " ".join(map(str, args)) + "\nexit_code=" +
        str(result.returncode) + "\n\nstdout:\n" + result.stdout +
        "\nstderr:\n" + result.stderr)
    safe = content.replace(str(Path.home()), "$HOME").replace("\r", "\n")
    (evidence / (label + ".log")).write_text(
        "\n".join(line.rstrip() for line in safe.splitlines()) + "\n")
    if result.returncode:
        raise RuntimeError(f"{label}: exit {result.returncode}")
    return result


def frame_hashes(output):
    return re.findall(r"^0,\s*\d+,\s*\d+,\s*\d+,\s*\d+,\s*([0-9a-f]{32})$",
                      output, re.MULTILINE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--x265-12", required=True)
    parser.add_argument("--ffmpeg-cuvid", required=True)
    parser.add_argument("--chroma", choices=("420", "444"), default="420")
    parser.add_argument("--player", help="installed P16 player command for bounded 12-bit playback")
    parser.add_argument("--vulkan-player", help="installed player with explicit Vulkan Video decode")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    label = "hevc12" if args.chroma == "420" else "hevc44412"
    pixel_format = "yuv420p12le" if args.chroma == "420" else "yuv444p12le"
    x265_chroma = "i420" if args.chroma == "420" else "i444"
    with tempfile.TemporaryDirectory(prefix="n1x-hevc12-") as directory:
        work = Path(directory)
        raw = work / "source.yuv"
        bitstream = work / "hevc12.hevc"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=size=320x180:rate=10", "-frames:v", "30",
             "-pix_fmt", pixel_format, "-f", "rawvideo", "-y", str(raw)],
            f"{label}-source", args.output_dir)
        run([args.x265_12, "--input", str(raw), "--input-res", "320x180",
             "--fps", "10", "--input-depth", "12", "--input-csp", x265_chroma,
             "--frames", "30", "--preset", "ultrafast", "--crf", "22",
             "--output", str(bitstream)], f"{label}-x265", args.output_dir)
        probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-count_frames", "-show_entries",
                     "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames",
                     "-of", "json", str(bitstream)],
                    f"{label}-probe", args.output_dir)
        stream = json.loads(probe.stdout)["streams"][0]
        if (stream.get("codec_name"), stream.get("profile"),
            stream.get("pix_fmt"), stream.get("nb_read_frames")) != (
                "hevc", "Rext", pixel_format, "30"):
            raise RuntimeError(f"invalid 12-bit fixture: {stream}")

        software = run(["ffmpeg", "-hide_banner", "-loglevel", "verbose",
                        "-i", str(bitstream), "-frames:v", "30", "-pix_fmt",
                        pixel_format, "-f", "framemd5", "-"],
                       f"{label}-software", args.output_dir)
        cuvid = run([args.ffmpeg_cuvid, "-hide_banner", "-loglevel", "verbose",
                     "-c:v", "hevc_cuvid", "-i", str(bitstream),
                     "-frames:v", "30", "-pix_fmt", pixel_format,
                     "-f", "framemd5", "-"],
                    f"{label}-cuvid", args.output_dir)
        software_hashes = frame_hashes(software.stdout)
        cuvid_hashes = frame_hashes(cuvid.stdout)
        if (len(software_hashes) != 30 or software_hashes != cuvid_hashes or
                "12 bit: supported: 1" not in cuvid.stderr or
                "hevc_cuvid" not in cuvid.stderr):
            raise RuntimeError("CUVID 12-bit pixel comparison or selection failed")

        vaapi = run(["ffmpeg", "-hide_banner", "-loglevel", "verbose",
                     "-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128",
                     "-hwaccel_output_format", "vaapi", "-i", str(bitstream),
                     "-frames:v", "30", "-f", "null", "-"],
                    f"{label}-vaapi", args.output_dir,
                    env={"LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"})
        if ("VA-API NVDEC driver [direct backend]" not in vaapi.stderr or
                "pixfmt:vaapi" not in vaapi.stderr or
                not re.search(r"frame=\s*30\b", vaapi.stderr)):
            raise RuntimeError("VA-API 12-bit hardware-frame decode not confirmed")
        player_result = None
        if args.player:
            player = subprocess.run(
                [args.player, str(bitstream), "--no-config", "--no-audio",
                 "--frames=30", "--force-window=yes", "--autofit=640x360"],
                capture_output=True, text=True, check=False, timeout=18,
                env={**os.environ, "LIBVA_DRIVER_NAME": "nvidia",
                     "NVD_BACKEND": "direct"})
            selected = [line for line in player.stdout.splitlines()
                        if any(term in line for term in
                               ("Using hardware decoding", "VO:", "No video PTS",
                                "Exiting..."))]
            (args.output_dir / f"{label}-player.log").write_text(
                "exit_code=" + str(player.returncode) + "\n" +
                "\n".join(selected) + "\n")
            surface = re.search(r"VO: \[gpu-next\].*vaapi\[([^]]+)\]", player.stdout)
            if (player.returncode != 0 or
                    "Using hardware decoding (vaapi)." not in player.stdout or
                    surface is None or
                    (args.chroma == "420" and surface.group(1) != "p012") or
                    "Exiting... (End of file)" not in player.stdout):
                raise RuntimeError("installed player did not finish 12-bit VA-API playback")
            player_result = {"status": "pass" if args.chroma == "420" else "playback_only",
                             "command": args.player,
                             "backend": "VA-API -> gpu-next", "frames_limit": 30,
                             "reported_surface_format": surface.group(1),
                             "precision": "12-bit surface reported" if args.chroma == "420"
                             else "12-bit surface preservation not established",
                             "raw_bitstream_timestamps": "missing; mpv synthesized PTS"}
        vulkan_player_result = None
        if args.vulkan_player:
            player = subprocess.run(
                [args.vulkan_player, str(bitstream), "--no-config", "--no-audio",
                 "--frames=30", "--force-window=yes", "--autofit=640x360",
                 "--hwdec=hevc-vulkan"],
                capture_output=True, text=True, check=False, timeout=18)
            selected = [line for line in player.stdout.splitlines()
                        if any(term in line for term in
                               ("Using hardware decoding", "VO:", "No video PTS",
                                "Exiting..."))]
            (args.output_dir / f"{label}-player-vulkan.log").write_text(
                "exit_code=" + str(player.returncode) + "\n" +
                "\n".join(selected) + "\n")
            surface = re.search(r"VO: \[gpu-next\].*vulkan\[([^]]+)\]", player.stdout)
            expected = "p012" if args.chroma == "420" else "p412"
            if (player.returncode != 0 or
                    "Using hardware decoding (vulkan)." not in player.stdout or
                    surface is None or surface.group(1) != expected or
                    "Exiting... (End of file)" not in player.stdout):
                raise RuntimeError("installed player did not finish 12-bit Vulkan decode")
            vulkan_player_result = {
                "status": "pass", "command": args.vulkan_player,
                "backend": "Vulkan Video -> gpu-next", "frames_limit": 30,
                "reported_surface_format": surface.group(1),
                "raw_bitstream_timestamps": "missing; mpv synthesized PTS"}
        result = {
            "status": "pass", "machine": "ASUS ProArt P16 H7607BA",
            "chroma": args.chroma,
            "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
            "nvidia_driver": subprocess.check_output(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                text=True, timeout=10).strip(), "fixture": stream,
            "fixture_sha256": sha256(bitstream), "frames": 30,
            "cuvid_matches_software_framemd5": True,
            "frame_hashes_sha256": hashlib.sha256(
                "\n".join(software_hashes).encode()).hexdigest(),
            "vaapi_hardware_frames": 30,
            "x265_12_binary_sha256": sha256(args.x265_12),
            "ffmpeg_cuvid_binary_sha256": sha256(args.ffmpeg_cuvid),
            "player": player_result,
            "vulkan_player": vulkan_player_result,
            "limits": "VA-API frames counted on hardware surfaces; pixel comparison used direct CUVID because VA-API hwdownload was not qualified.",
        }
    (args.output_dir / f"{label}-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
