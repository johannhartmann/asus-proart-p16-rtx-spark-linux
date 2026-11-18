#!/usr/bin/env python3
"""Generate a 12-bit HEVC fixture and compare CUVID pixels with software decode."""

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
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="n1x-hevc12-") as directory:
        work = Path(directory)
        raw = work / "source.yuv"
        bitstream = work / "hevc12.hevc"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=size=320x180:rate=10", "-frames:v", "30",
             "-pix_fmt", "yuv420p12le", "-f", "rawvideo", "-y", str(raw)],
            "hevc12-source", args.output_dir)
        run([args.x265_12, "--input", str(raw), "--input-res", "320x180",
             "--fps", "10", "--input-depth", "12", "--input-csp", "i420",
             "--frames", "30", "--preset", "ultrafast", "--crf", "22",
             "--output", str(bitstream)], "hevc12-x265", args.output_dir)
        probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-count_frames", "-show_entries",
                     "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames",
                     "-of", "json", str(bitstream)],
                    "hevc12-probe", args.output_dir)
        stream = json.loads(probe.stdout)["streams"][0]
        if (stream.get("codec_name"), stream.get("profile"),
            stream.get("pix_fmt"), stream.get("nb_read_frames")) != (
                "hevc", "Rext", "yuv420p12le", "30"):
            raise RuntimeError(f"invalid 12-bit fixture: {stream}")

        software = run(["ffmpeg", "-hide_banner", "-loglevel", "verbose",
                        "-i", str(bitstream), "-frames:v", "30", "-pix_fmt",
                        "yuv420p12le", "-f", "framemd5", "-"],
                       "hevc12-software", args.output_dir)
        cuvid = run([args.ffmpeg_cuvid, "-hide_banner", "-loglevel", "verbose",
                     "-c:v", "hevc_cuvid", "-i", str(bitstream),
                     "-frames:v", "30", "-pix_fmt", "yuv420p12le",
                     "-f", "framemd5", "-"],
                    "hevc12-cuvid", args.output_dir)
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
                    "hevc12-vaapi", args.output_dir,
                    env={"LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"})
        if ("VA-API NVDEC driver [direct backend]" not in vaapi.stderr or
                "pixfmt:vaapi" not in vaapi.stderr or
                not re.search(r"frame=\s*30\b", vaapi.stderr)):
            raise RuntimeError("VA-API 12-bit hardware-frame decode not confirmed")
        result = {
            "status": "pass", "machine": "ASUS ProArt P16 H7607BA",
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
            "limits": "VA-API frames counted on hardware surfaces; pixel comparison used direct CUVID because VA-API hwdownload was not qualified.",
        }
    (args.output_dir / "hevc12-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
