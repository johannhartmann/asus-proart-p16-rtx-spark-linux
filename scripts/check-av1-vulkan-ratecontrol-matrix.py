#!/usr/bin/env python3
"""Cross-decode N1X AV1 Vulkan rate-control outputs with two software decoders."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


CASES = {
    "default": [],
    "driver": ["-rc_mode", "driver"],
    "driver_bitrate_2m": ["-rc_mode", "driver", "-b:v", "2M"],
    "bitrate_2m": ["-b:v", "2M"],
    "cqp_10": ["-rc_mode", "cqp", "-qp", "10"],
    "cqp_30": ["-rc_mode", "cqp", "-qp", "30"],
    "qp_30_auto": ["-qp", "30"],
    "quality_1": ["-quality", "1"],
    "tune_hq": ["-tune", "hq"],
    "usage_record": ["-usage", "record"],
}
EXTENDED = {
    "bitrate_5m": ["-b:v", "5M"],
    "bitrate_10m": ["-b:v", "10M"],
    "bitrate_20m": ["-b:v", "20M"],
    "bitrate_40m": ["-b:v", "40M"],
    "cqp_15": ["-rc_mode", "cqp", "-qp", "15"],
    "cqp_20": ["-rc_mode", "cqp", "-qp", "20"],
    "cqp_25": ["-rc_mode", "cqp", "-qp", "25"],
}
FRAMES = 24


def run(command):
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=45, check=False)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_dav1d(ffmpeg, bitstream):
    done = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-c:v", "libdav1d",
                "-i", str(bitstream), "-f", "framemd5", "-"])
    lines = done.stdout.splitlines()
    hashes = [line for line in lines if re.match(r"^\d+,", line)]
    errors = [line.strip() for line in done.stderr.splitlines() if
              re.search(r"error|invalid|corrupt|failed", line, re.I)]
    return {"exit_code": done.returncode, "decoded_frames": len(hashes),
            "error_lines": errors[:6],
            "pass": done.returncode == 0 and len(hashes) == FRAMES and not errors}


def decode_aom(bitstream):
    done = run(["/usr/bin/aomdec", "--noblit", "--progress", "--summary",
                str(bitstream)])
    counts = re.findall(r"(\d+) decoded frames/\d+ showed frames", done.stderr)
    decoded = int(counts[-1]) if counts else None
    errors = [line.strip() for line in done.stderr.replace("\r", "\n").splitlines()
              if re.search(r"error|invalid|corrupt|failed", line, re.I)]
    return {"exit_code": done.returncode, "decoded_frames": decoded,
            "error_lines": errors[:6],
            "pass": done.returncode == 0 and decoded == FRAMES and not errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="/usr/bin/ffmpeg")
    parser.add_argument("--extended-only", action="store_true",
                        help="run the baseline and additional bitrate/CQP cases")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    ffmpeg = str(Path(args.ffmpeg).resolve(strict=True))
    cases = {"default": CASES["default"], **EXTENDED} if args.extended_only else CASES
    results = {}
    with tempfile.TemporaryDirectory(prefix="p16-av1-vulkan-rc-matrix-") as folder:
        work = Path(folder)
        for name, options in cases.items():
            bitstream = work / f"{name}.ivf"
            encoded = run([
                ffmpeg, "-hide_banner", "-loglevel", "verbose",
                "-init_hw_device", "vulkan=vk:0", "-filter_hw_device", "vk",
                "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24",
                "-frames:v", str(FRAMES), "-vf", "format=nv12,hwupload",
                "-c:v", "av1_vulkan", *options, "-f", "ivf", "-y",
                str(bitstream)])
            case = {
                "options": options,
                "encode_exit_code": encoded.returncode,
                "n1x_vulkan_device_logged": "NVIDIA RTX Spark N1X" in encoded.stderr,
                "encoded_bytes": bitstream.stat().st_size if bitstream.exists() else None,
                "encoded_sha256": sha256(bitstream) if bitstream.exists() else None,
                "encode_error_lines": [line.strip() for line in
                                       encoded.stderr.splitlines() if
                                       re.search(r"error|invalid|corrupt|failed", line, re.I)][:6],
            }
            if encoded.returncode == 0:
                case["decoders"] = {"libdav1d": decode_dav1d(ffmpeg, bitstream),
                                    "libaom": decode_aom(bitstream)}
            else:
                case["decoders"] = None
            case["bitstream_pass"] = (encoded.returncode == 0 and
                                      case["n1x_vulkan_device_logged"] and
                                      case["decoders"] is not None and
                                      all(item["pass"] for item in
                                          case["decoders"].values()))
            results[name] = case
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "nvidia_driver": run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                              "--format=csv,noheader"]).stdout.strip(),
        "ffmpeg": ffmpeg,
        "ffmpeg_sha256": sha256(Path(ffmpeg)),
        "aomdec_sha256": sha256(Path("/usr/bin/aomdec")),
        "fixture": "testsrc2 1280x720/24, 24 frames, NV12",
        "extended_only": args.extended_only,
        "cases": results,
        "passing_modes": [name for name, case in results.items() if case["bitstream_pass"]],
        "baseline_pass": results["default"]["bitstream_pass"],
        "temporary_pixels_or_bitstreams_retained": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"baseline_pass": result["baseline_pass"],
                      "passing_modes": result["passing_modes"],
                      "cases": {name: {"encode": case["encode_exit_code"],
                                       "decoders": {codec: decoded["decoded_frames"]
                                                    for codec, decoded in
                                                    (case["decoders"] or {}).items()}}
                                for name, case in results.items()}}))
    return 0 if result["baseline_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
