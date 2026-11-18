#!/usr/bin/env python3
"""Measure midpoint artifacts on a moving foreground over fixed background."""

import argparse
import json
from pathlib import Path
import random
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    width, height = 320, 180
    rng = random.Random(8701)
    background = bytes(rng.randrange(20, 236) for _ in range(width * height * 3))
    foreground = bytes(rng.randrange(20, 236) for _ in range(48 * 48 * 3))

    def frame(square_x):
        result = bytearray(background)
        for y in range(60, 108):
            for x in range(square_x, square_x + 48):
                offset = (y * width + x) * 3
                source = ((y - 60) * 48 + x - square_x) * 3
                result[offset:offset + 3] = foreground[source:source + 3]
        return bytes(result)

    first, expected, last = frame(96), frame(104), frame(112)
    probe = subprocess.run(
        ["/usr/bin/p16-nvof-analyze", "--interpolate", str(width), str(height), "1"],
        input=first + last, capture_output=True, check=True, timeout=10)
    frame_size = len(first)
    if len(probe.stdout) != 3 * frame_size:
        raise RuntimeError("NVOFA emitted an unexpected frame count")
    middle = probe.stdout[frame_size:2 * frame_size]
    crossfade = bytes((a + b) // 2 for a, b in zip(first, last))

    def mse(actual, region):
        total, count = 0, 0
        for y in range(*region[2:]):
            for x in range(*region[:2]):
                for c in range(3):
                    index = (y * width + x) * 3 + c
                    total += (actual[index] - expected[index]) ** 2
                    count += 1
        return total / count

    region = (80, 176, 48, 120)
    regions = {
        "trailing_uncover": (96, 104, 60, 108),
        "new_foreground_left": (104, 112, 60, 108),
        "foreground_overlap": (112, 144, 60, 108),
        "new_foreground_right": (144, 152, 60, 108),
        "leading_uncover": (152, 160, 60, 108),
        "static_background": (80, 96, 60, 108),
    }
    report = {
        "fixture": "48x48 textured foreground moves 16 pixels over a fixed textured background",
        "dimensions": [width, height], "region": list(region),
        "nvof_midpoint_mse": mse(middle, region),
        "crossfade_midpoint_mse": mse(crossfade, region),
        "region_mse": {name: {"nvof": mse(middle, bounds),
                               "crossfade": mse(crossfade, bounds)}
                       for name, bounds in regions.items()},
        "source_frames_preserved": probe.stdout[:frame_size] == first and
        probe.stdout[2 * frame_size:] == last,
        "nvof_pairs_logged": "nvof_interpolated_pairs=1" in probe.stderr.decode(errors="replace"),
        "frames_retained": False,
    }
    report["pass"] = (report["source_frames_preserved"] and
                      report["nvof_pairs_logged"] and
                      report["nvof_midpoint_mse"] <
                      report["crossfade_midpoint_mse"] / 2 and
                      report["region_mse"]["static_background"]["nvof"] < 100)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
