#!/usr/bin/env python3
"""Qualify installed HDR10 playback through mpv, Hyprland and NVIDIA DRM."""

import argparse
import hashlib
import json
import re
import socket
import subprocess
import time
from pathlib import Path


def output(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def state():
    monitor = next(m for m in json.loads(output("hyprctl", "monitors", "-j"))
                   if m["name"] == "eDP-1")
    drm = output("modetest", "-M", "nvidia-drm", "-c")
    first = re.search(r"(?m)^\d+\s+\d+\s+connected\s+eDP-1\b", drm)
    if not first:
        raise RuntimeError("DRM eDP-1 connector missing")
    next_connector = re.search(r"(?m)^\d+\s+\d+\s+(?:connected|disconnected)\s+\S+", drm[first.end():])
    block = drm[first.end(): first.end() + next_connector.start()] if next_connector else drm[first.end():]
    colorspace = re.search(r"\bColorspace:\s*\n(?:.*\n)*?\s*value:\s*(\d+)", block)
    metadata = re.search(r"\bHDR_OUTPUT_METADATA:\s*\n(?:.*\n)*?\s*value:\s*\n((?:\s*[0-9a-f]{32}\s*\n)+)", block)
    blob = "".join(metadata.group(1).split()) if metadata else ""
    return {"monitor": {key: monitor.get(key) for key in
                        ("name", "description", "currentFormat", "colorManagementPreset")},
            "drmColorspace": int(colorspace.group(1)) if colorspace else None,
            "drmHdrMetadataHex": blob,
            "drmHdrMetadataNonzero": bool(blob and int(blob, 16))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path, help="local HDR10 HEVC test stream")
    parser.add_argument("result", type=Path, help="JSON evidence path")
    args = parser.parse_args()
    args.result.parent.mkdir(parents=True, exist_ok=True)
    log = args.result.with_suffix(".mpv.log")
    ipc = args.result.with_suffix(".mpv.sock")
    ipc.unlink(missing_ok=True)
    before = state()
    cmd = ["/usr/bin/p16-hdr-play", str(args.video), "--loop-file=inf", "--no-audio",
           "--input-ipc-server=" + str(ipc),
           "--msg-level=all=v", "--log-file=" + str(log)]
    with args.result.with_suffix(".launcher.log").open("w") as launcher_log:
        proc = subprocess.Popen(cmd, stdout=launcher_log, stderr=subprocess.STDOUT)
        during = None
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f"launcher exited early: {proc.returncode}")
                sample = state()
                if (sample["monitor"]["currentFormat"] == "XBGR2101010"
                        and sample["monitor"]["colorManagementPreset"] == "hdr"
                        and sample["drmColorspace"] == 9
                        and sample["drmHdrMetadataNonzero"]):
                    during = sample
                    break
                time.sleep(0.25)
            if during is None:
                raise RuntimeError("HDR DRM signal did not appear within 20 seconds")
            markers_to_wait = ("Using hardware decoding (vulkan)", "vulkan[p010]",
                               "transfer: pq, primaries: bt.2020",
                               "Picked surface configuration 30: VK_FORMAT_A2B10G10R10_UNORM_PACK32 + VK_COLOR_SPACE_HDR10_ST2084_EXT")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f"launcher exited before video output: {proc.returncode}")
                if log.exists() and all(term in log.read_text(errors="replace") for term in markers_to_wait):
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("mpv did not decode and present the HDR10 stream")
            sock = socket.socket(socket.AF_UNIX)
            deadline = time.monotonic() + 10
            while not ipc.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            sock.connect(str(ipc))
            sock.sendall(b'{"command":["quit"]}\n')
            sock.close()
            returncode = proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=15)
            ipc.unlink(missing_ok=True)
    after = state()
    errors = output("hyprctl", "configerrors").strip()
    mpv_log = log.read_text(errors="replace")
    patterns = markers_to_wait
    markers = {term: term in mpv_log for term in patterns}
    summary = {"fixtureSha256": hashlib.sha256(args.video.read_bytes()).hexdigest(),
               "package": output("pacman", "-Q", "p16-media-tools").strip(),
               "launcherSha256": hashlib.sha256(Path("/usr/bin/p16-hdr-play").read_bytes()).hexdigest(),
               "before": before, "during": during, "after": after,
               "hyprlandConfigErrors": errors, "mpvMarkers": markers,
               "launcherExit": returncode,
               "pass": returncode == 0 and not errors and all(markers.values()) and
                       before["monitor"]["colorManagementPreset"] == "srgb" and
                       before["drmColorspace"] == 0 and
                       not before["drmHdrMetadataNonzero"] and
                       after["monitor"]["colorManagementPreset"] == "srgb" and
                       after["drmColorspace"] == 0 and
                       not after["drmHdrMetadataNonzero"]}
    args.result.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"pass": summary["pass"], "result": str(args.result)}))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
