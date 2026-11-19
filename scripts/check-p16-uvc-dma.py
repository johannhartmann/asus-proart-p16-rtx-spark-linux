#!/usr/bin/env python3
"""Capture the P16 cameras and check UVC URB sizes against the XHCI DMA limit.

Enable uvcvideo trace bit 1024 before running and restore the original setting
afterwards. The caller performs those privileged writes through desktop polkit.
No image or video data is kept.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from collections import Counter


RGB = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.0-video-index0"
IR = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.2-video-index0"
STREAMCAM = "/dev/v4l/by-path/platform-NVDA8000:00-usb-0:1.1:1.0-video-index0"
CASES = (
    ("rgb-720p", RGB, "mjpeg", "1280x720", 30, 60),
    ("rgb-1080p", RGB, "mjpeg", "1920x1080", 30, 60),
    ("ir-360p", IR, "gray", "360x360", 15, 30),
)
URB = re.compile(r"uvcvideo\s+(\S+?):\s+Allocated \d+ URB buffers of (\d+)x(\d+) bytes each")
LIMIT = re.compile(r"uvcvideo\s+(\S+?):\s+Limiting URB to (\d+) packets")
WARNINGS = ("DMA-API:", "WARNING:", "BUG:", "KASAN:", "NVRM: Xid")
RGB_PACKET_BYTES = 2940
IR_PACKET_BYTES = 1176
# StreamCam 1920x1080/30 MJPEG selects alternate setting 7, as measured in
# uvc-streamcam-urb-size-current-boot.json. The 3072-byte setting is 720p.
STREAMCAM_1080P_MJPEG_PACKET_BYTES = 6144


def interface_for(device):
    video = Path(device).resolve().name
    path = (Path("/sys/class/video4linux") / video / "device").resolve(strict=True)
    if not re.fullmatch(r"\d+-[\d.]+:\d+\.\d+", path.name):
        raise RuntimeError(f"could not identify UVC interface for {device}")
    return path.name


def capture(name, device, fmt, size, fps, frames, directory):
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-f", "v4l2",
               "-input_format", fmt, "-framerate", str(fps),
               "-video_size", size, "-i", device, "-frames:v", str(frames),
               "-f", "null", "-"]
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=max(30, frames // fps + 20), check=False)
        log = done.stdout + done.stderr
        code = done.returncode
    except subprocess.TimeoutExpired as error:
        chunks = (error.stdout, error.stderr)
        log = "".join(chunk.decode(errors="replace") if isinstance(chunk, bytes)
                      else chunk or "" for chunk in chunks)
        code = 124
    (directory / f"{name}.log").write_text(log)
    counts = re.findall(r"frame=\s*(\d+)", log)
    return {"command": command, "exit_code": code,
            "usb_interface": interface_for(device),
            "frames": int(counts[-1]) if counts else 0,
            "expected_frames": frames}


def allocations_from_trace(uvc, max_segment):
    allocations = []
    for line in uvc:
        match = URB.search(line)
        if match:
            interface = match.group(1)
            packets, packet_bytes = map(int, match.groups()[1:])
            requested = packets * packet_bytes
            rounded = (requested + 4095) // 4096 * 4096
            allocations.append({"usb_interface": interface,
                                "packets": packets, "packet_bytes": packet_bytes,
                                "requested_bytes": requested,
                                "page_rounded_bytes": rounded,
                                "within_dma_limit": rounded <= max_segment})
    return allocations


def evaluate(result):
    max_segment = result["max_dma_segment_bytes"]
    allocations = allocations_from_trace(result["uvc_trace_lines"], max_segment)
    if allocations != result["allocations"]:
        raise RuntimeError("recorded allocations differ from raw UVC trace")
    rgb_interface = result["cases"]["rgb-720p"]["usb_interface"]
    ir_interface = result["cases"]["ir-360p"]["usb_interface"]
    streamcam_interface = (result["cases"]["streamcam-1080p"]["usb_interface"]
                           if result["streamcam_included"] else None)
    expected_allocations = Counter({rgb_interface: 2, ir_interface: 1})
    expected_packet_bytes = {rgb_interface: RGB_PACKET_BYTES,
                             ir_interface: IR_PACKET_BYTES}
    if streamcam_interface:
        expected_allocations[streamcam_interface] = 1
        expected_packet_bytes[streamcam_interface] = STREAMCAM_1080P_MJPEG_PACKET_BYTES
    observed_allocations = Counter(item["usb_interface"] for item in allocations)
    limits = [(match.group(1), int(match.group(2)))
              for line in result["uvc_trace_lines"]
              if (match := LIMIT.search(line))]
    expected_rgb_packets = max_segment // 4096 * 4096 // RGB_PACKET_BYTES
    rgb_capped = limits.count((rgb_interface, expected_rgb_packets)) >= 2
    expected_streamcam_packets = (max_segment // 4096 * 4096 //
                                  STREAMCAM_1080P_MJPEG_PACKET_BYTES)
    streamcam_capped = not result["streamcam_included"] or (
        (streamcam_interface, expected_streamcam_packets) in limits)
    interfaces_covered = all(observed_allocations[interface] >= count
                             for interface, count in expected_allocations.items())
    packet_sizes_match = all(
        item["packet_bytes"] == expected_packet_bytes[item["usb_interface"]]
        for item in allocations
        if item["usb_interface"] in expected_packet_bytes)
    result["interface_checks"] = {
        "expected_allocations": dict(expected_allocations),
        "observed_allocations": dict(observed_allocations),
        "expected_packet_bytes": expected_packet_bytes,
        "interfaces_covered": interfaces_covered,
        "packet_sizes_match": packet_sizes_match,
        "rgb_capped": rgb_capped,
        "streamcam_capped": streamcam_capped,
    }
    result["pass"] = (all(item["exit_code"] == 0 and
                          item["frames"] == item["expected_frames"]
                          for item in result["cases"].values()) and
                      interfaces_covered and packet_sizes_match and
                      all(item["within_dma_limit"] for item in allocations) and
                      rgb_capped and streamcam_capped and
                      not result["new_kernel_warnings"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-segment", type=int, default=65536)
    parser.add_argument("--include-streamcam", action="store_true",
                        help="also capture the external Logitech host at 1080p MJPEG")
    parser.add_argument("--recheck", type=Path,
                        help="re-evaluate a prior raw trace without capture or root")
    parser.add_argument("--output", type=Path,
                        help="new receipt path for --recheck")
    args = parser.parse_args()
    if args.recheck:
        if args.output_dir or not args.output or args.output.exists():
            parser.error("--recheck needs a new --output and no --output-dir")
        raw = args.recheck.read_bytes()
        result = json.loads(raw)
        if result["max_dma_segment_bytes"] != args.max_segment:
            parser.error("recheck DMA limit differs from original capture")
        original_pass = result["pass"]
        result = evaluate(result)
        result["rechecked_at"] = datetime.now(timezone.utc).isoformat()
        result["rechecked_from"] = str(args.recheck)
        result["original_sha256"] = hashlib.sha256(raw).hexdigest()
        result["original_pass"] = original_pass
        result["packet_size_correction"] = {
            "case": "streamcam-1080p", "old_expected_bytes": 3072,
            "correct_expected_bytes": STREAMCAM_1080P_MJPEG_PACKET_BYTES,
            "basis": "prior StreamCam 1080p MJPEG alternate-setting 7 trace"}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"pass": result["pass"],
                          "packet_sizes_match": result["interface_checks"]["packet_sizes_match"],
                          "streamcam_capped": result["interface_checks"]["streamcam_capped"]}))
        return 0 if result["pass"] else 1
    if args.output_dir is None or args.output is not None:
        parser.error("capture needs --output-dir and no --output")
    trace = int(Path("/sys/module/uvcvideo/parameters/trace").read_text().strip())
    if not trace & 1024:
        parser.error("enable uvcvideo trace bit 1024 before this check")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    since = int(time.time())
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "kernel": subprocess.check_output(["uname", "-r"], text=True).strip(),
        "trace_during": trace,
        "max_dma_segment_bytes": args.max_segment,
        "camera_pixels_retained": False,
        "streamcam_included": args.include_streamcam,
        "cases": {},
    }
    cases = CASES + (("streamcam-1080p", STREAMCAM, "mjpeg", "1920x1080", 30, 60),) \
        if args.include_streamcam else CASES
    for case in cases:
        result["cases"][case[0]] = capture(*case, args.output_dir)
    journal = subprocess.run(
        ["journalctl", "-k", "-b", "--since", f"@{since}", "--no-pager",
         "-o", "short-iso"], capture_output=True, text=True, check=True,
        timeout=15).stdout.splitlines()
    uvc = [line for line in journal if "uvcvideo" in line and
           ("Limiting URB" in line or "Allocated " in line)]
    warnings = [line for line in journal if any(token in line for token in WARNINGS)]
    allocations = allocations_from_trace(uvc, args.max_segment)
    result["uvc_trace_lines"] = uvc
    result["allocations"] = allocations
    result["new_kernel_warnings"] = warnings
    result = evaluate(result)
    (args.output_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "cases": result["cases"],
                      "allocations": allocations, "warnings": len(warnings)}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
