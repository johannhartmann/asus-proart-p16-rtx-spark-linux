#!/usr/bin/env python3
"""Compare default and explicit-bitrate N1X AV1 Vulkan Video output."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def run(command):
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"source": "testsrc2 1280x720 24 fps, 24 frames",
              "encoder": "distribution FFmpeg av1_vulkan on RTX Spark N1X",
              "cases": {}, "fixture_pixels_retained": False}
    with tempfile.TemporaryDirectory(prefix="p16-av1-vulkan-") as temporary:
        cases = (("default", []),
                 ("bitrate_2m", ["-b:v", "2M"]),
                 ("bitrate_2m_cbr", ["-b:v", "2M", "-rc_mode", "cbr"]),
                 ("bitrate_2m_vbr", ["-b:v", "2M", "-rc_mode", "vbr"]),
                 ("cqp_30", ["-rc_mode", "cqp", "-qp", "30"]))
        for name, options in cases:
            output = Path(temporary) / f"{name}.mkv"
            encoded = run([
                "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                "-init_hw_device", "vulkan=vk:0", "-filter_hw_device", "vk",
                "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24",
                "-frames:v", "24", "-vf", "format=nv12,hwupload",
                "-c:v", "av1_vulkan", *options, "-y", str(output)])
            decoded = run(["/usr/bin/ffmpeg", "-v", "error", "-i", str(output),
                           "-f", "null", "-"]) if encoded.returncode == 0 else None
            result["cases"][name] = {
                "encode_exit_code": encoded.returncode,
                "decode_exit_code": decoded.returncode if decoded else None,
                "decode_errors": [re.sub(r"@ 0x[0-9a-f]+", "@ $PTR", line)
                                  for line in (decoded.stderr if decoded else "").splitlines()
                                  if "Error" in line or "error" in line][:4],
            }
    result["pass"] = all(case["encode_exit_code"] == 0 and
                         case["decode_exit_code"] == 0 for case in result["cases"].values())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
