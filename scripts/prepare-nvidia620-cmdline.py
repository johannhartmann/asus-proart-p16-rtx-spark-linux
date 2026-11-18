#!/usr/bin/env python3
"""Derive an isolated 620 UKI command line from a verified kernel38 UKI."""

import argparse
import importlib.util
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "p16_dsp_cmdline", HERE / "verify-dsp-boot-cmdline.py")
DSP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DSP)


def rewrite(cmdline, release, target_subvolume):
    source = DSP.check_cmdline(cmdline, release, release, "@", "source")
    if not source["pass"]:
        raise ValueError("source UKI lacks the qualified kernel38 audio/root profile")
    if not re.fullmatch(r"@[A-Za-z0-9._+-]+", target_subvolume):
        raise ValueError("target subvolume must be a named @ subvolume")
    old = "rootflags=subvol=@"
    new = "rootflags=subvol=" + target_subvolume
    candidate, replacements = re.subn(r"(?<!\S)rootflags=subvol=@(?=\s|$)",
                                      new, cmdline)
    if replacements != 1:
        raise ValueError("source UKI must contain exactly one rootflags=subvol=@")
    result = DSP.check_cmdline(candidate, release, release,
                               target_subvolume, "candidate")
    if not result["pass"] or old in candidate.split():
        raise ValueError("candidate UKI command line failed root/audio check")
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-uki", required=True, type=Path)
    parser.add_argument("--release", required=True)
    parser.add_argument("--target-subvolume", default="@nvidia620")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output path")
    sections = DSP.BOOT.sections(args.source_uki)
    release = sections[".uname"].rstrip(b"\0\n").decode()
    if release != args.release:
        parser.error("source UKI has a different kernel release")
    cmdline = sections[".cmdline"].rstrip(b"\0\n").decode()
    candidate = rewrite(cmdline, release, args.target_subvolume)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(candidate + "\n")
    print("Candidate cmdline validated:", args.target_subvolume, release,
          args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
