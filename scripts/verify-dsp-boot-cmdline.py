#!/usr/bin/env python3
"""Verify that a staged P16 UKI will select the qualified ADSP audio route."""

import argparse
import importlib.util
import json
from pathlib import Path


_spec = importlib.util.spec_from_file_location(
    "p16_verify_boot", Path(__file__).with_name("verify-boot.py"))
BOOT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BOOT)
REQUIRED = (
    "n1x_adsp.auto_boot=1",
    "n1x_adsp.enable_retention_sleep=1",
    "snd_soc_mt8901_afe.dsp_playback=1",
    "snd_soc_mt8901_afe.dsp_capture=1",
    "mt8901_acp_sdw_legacy_mach.dsp_playback=1",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    sections = BOOT.sections(args.image)
    release = sections[".uname"].rstrip(b"\0\n").decode()
    cmdline = sections[".cmdline"].rstrip(b"\0\n").decode()
    tokens = cmdline.split()
    missing = [token for token in REQUIRED if tokens.count(token) != 1]
    blacklist = [token.split("=", 1)[1] for token in tokens
                 if token.startswith("module_blacklist=")]
    placeholder_blocked = any("snd_sof_mt8901" in value.split(",")
                              for value in blacklist)
    root_preserved = "rootflags=subvol=@" in tokens
    passed = (release == args.release and not missing and
              placeholder_blocked and root_preserved)
    result = {"image": str(args.image), "release": release,
              "required_dsp_tokens_present_once": not missing,
              "missing_or_duplicated": missing,
              "placeholder_sof_blacklisted": placeholder_blocked,
              "root_subvolume_preserved": root_preserved,
              "pass": passed}
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
