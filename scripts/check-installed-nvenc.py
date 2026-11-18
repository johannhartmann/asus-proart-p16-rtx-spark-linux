#!/usr/bin/env python3
"""Probe all three NVENC codecs through the installed isolated FFmpeg binary."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="/usr/bin/ffmpeg-n1x")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "ffmpeg": args.ffmpeg,
        "ffmpeg_sha256": hashlib.sha256(Path(args.ffmpeg).read_bytes()).hexdigest(),
        "package": subprocess.check_output(
            ["pacman", "-Q", "ffmpeg-n1x-video"], text=True, timeout=10).strip(),
        "driver": subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            text=True, timeout=10).strip(),
        "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
        "codecs": {},
    }
    for codec in ("h264", "hevc", "av1"):
        command = [args.ffmpeg, "-hide_banner", "-loglevel", "verbose", "-f",
                   "lavfi", "-i", "testsrc2=size=320x180:rate=10", "-frames:v",
                   "10", "-c:v", f"{codec}_nvenc", "-f", "null", "-"]
        result = subprocess.run(command, capture_output=True, text=True,
                                check=False, timeout=20)
        log = "$ " + " ".join(command) + "\nexit_code=" + str(result.returncode)
        log += "\n\nstdout:\n" + result.stdout + "\nstderr:\n" + result.stderr
        (args.output_dir / f"installed-nvenc-{codec}.log").write_text(
            "\n".join(line.rstrip() for line in log.replace("\r", "\n").splitlines()) + "\n")
        encoded = result.returncode == 0 and re.search(r"frame=\s*10\b", result.stderr)
        report["codecs"][codec] = {
            "status": "pass" if encoded else "fail",
            "exit_code": result.returncode,
            "open_encode_session_error_21":
                "OpenEncodeSessionEx failed: incompatible client key (21)" in result.stderr,
        }
    report["status"] = "pass" if all(
        item["status"] == "pass" for item in report["codecs"].values()) else "fail"
    (args.output_dir / "installed-nvenc.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({codec: item["status"] for codec, item in report["codecs"].items()}))
    return int(report["status"] != "pass")


if __name__ == "__main__":
    sys.exit(main())
