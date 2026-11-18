#!/usr/bin/env python3
"""Record real P16 RGB camera frames through N1X Vulkan AV1 and cross-decode."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


FRAMES = 60
CAMERA = "/dev/v4l/by-path/platform-NVDA8001:00-usb-0:1:1.0-video-index0"


def run(command, timeout=45):
    return subprocess.run(command, capture_output=True, text=True,
                          check=False, timeout=timeout)


def save_log(path, command, result, work):
    content = ("$ " + " ".join(command) + "\nexit_code=" + str(result.returncode)
               + "\n\nstdout:\n" + result.stdout + "\nstderr:\n" + result.stderr)
    content = content.replace(str(work), "$WORKDIR").replace(str(Path.home()), "$HOME")
    path.write_text("\n".join(line.rstrip() for line in
                              content.replace("\r", "\n").splitlines()) + "\n")


def digest(path):
    hash_ = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            hash_.update(block)
    return hash_.hexdigest()


def last_count(pattern, text):
    matches = re.findall(pattern, text)
    return int(matches[-1]) if matches else None


def dynamic_framerate_value():
    result = run(["/usr/bin/v4l2-ctl", "-d", CAMERA, "--get-ctrl",
                  "exposure_dynamic_framerate"], timeout=10)
    if result.returncode:
        raise RuntimeError("could not read camera dynamic frame-rate control")
    match = re.search(r"exposure_dynamic_framerate:\s*([01])", result.stdout)
    if not match:
        raise RuntimeError("unexpected dynamic frame-rate control output")
    return int(match.group(1))


@contextmanager
def camera_framerate(locked):
    state = {"before": dynamic_framerate_value(), "lock_30fps_requested": locked}
    try:
        if locked:
            result = run(["/usr/bin/v4l2-ctl", "-d", CAMERA, "--set-ctrl",
                          "exposure_dynamic_framerate=0"], timeout=10)
            if result.returncode:
                raise RuntimeError("could not disable dynamic camera frame rate")
        state["during"] = dynamic_framerate_value()
        yield state
    finally:
        if locked:
            restored = run(["/usr/bin/v4l2-ctl", "-d", CAMERA, "--set-ctrl",
                            f"exposure_dynamic_framerate={state['before']}"], timeout=10)
            if restored.returncode:
                raise RuntimeError("could not restore camera dynamic frame-rate control")
        state["after"] = dynamic_framerate_value()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--lock-30fps", action="store_true",
                        help="temporarily disable dynamic exposure frame rate, then restore it")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("choose a new output directory")
    camera = Path(CAMERA)
    if not camera.exists() or "ASUS FHD webcam" not in Path(
            "/sys/class/video4linux/video0/name").read_text():
        parser.error("internal ASUS RGB camera path/name is not present")
    args.output_dir.mkdir(parents=True)
    with camera_framerate(args.lock_30fps) as control, \
            tempfile.TemporaryDirectory(prefix="p16-camera-av1-vulkan-") as directory:
        work = Path(directory)
        bitstream = work / "camera.ivf"
        encode = ["/usr/bin/ffmpeg", "-hide_banner", "-nostdin", "-loglevel",
                  "verbose", "-init_hw_device", "vulkan=vk:0",
                  "-filter_hw_device", "vk", "-f", "v4l2", "-input_format",
                  "mjpeg", "-framerate", "30", "-video_size", "1280x720",
                  "-i", str(camera), "-frames:v", str(FRAMES), "-vf",
                  "format=nv12,hwupload", "-c:v", "av1_vulkan", "-fps_mode",
                  "passthrough", "-f", "ivf", "-y", str(bitstream)]
        started = time.monotonic()
        encoded = run(encode)
        encode_wall = time.monotonic() - started
        save_log(args.output_dir / "camera-av1-encode.log", encode, encoded, work)
        if encoded.returncode:
            raise RuntimeError("camera Vulkan AV1 encode failed")
        probe = ["/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-count_frames", "-show_entries",
                 "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames:packet=pts_time",
                 "-of", "json", str(bitstream)]
        probed = run(probe)
        save_log(args.output_dir / "camera-av1-probe.log", probe, probed, work)
        if probed.returncode:
            raise RuntimeError("camera AV1 probe failed")
        metadata = json.loads(probed.stdout)
        stream = metadata["streams"][0]
        pts = [float(item["pts_time"]) for item in metadata.get("packets", [])
               if "pts_time" in item]
        dav1d = ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
                  "-c:v", "libdav1d", "-i", str(bitstream), "-f", "framemd5", "-"]
        decoded = run(dav1d)
        save_log(args.output_dir / "camera-av1-dav1d.log", dav1d, decoded, work)
        frame_hashes = re.findall(r"^0,\s*\d+,\s*\d+,\s*\d+,\s*\d+,\s*([0-9a-f]{32})$",
                                  decoded.stdout, re.MULTILINE)
        aom = ["/usr/bin/aomdec", "--noblit", "--progress", "--summary",
               str(bitstream)]
        decoded_aom = run(aom)
        save_log(args.output_dir / "camera-av1-libaom.log", aom, decoded_aom, work)
        input_frames = last_count(r"Input stream #0:0 \(video\): \d+ packets read \([^)]*\); (\d+) frames decoded",
                                  encoded.stderr)
        output_frames = last_count(r"Output stream #0:0 \(video\): (\d+) frames encoded",
                                   encoded.stderr)
        aom_frames = last_count(r"(\d+) decoded frames/\d+ showed frames",
                                decoded_aom.stderr)
        checks = {
            "n1x_vulkan_encoder": "NVIDIA RTX Spark N1X" in encoded.stderr and
                                   "av1_vulkan" in encoded.stderr,
            "camera_input_frames": input_frames == FRAMES,
            "encoded_output_frames": output_frames == FRAMES,
            "av1_main_720p": (stream.get("codec_name"), stream.get("profile"),
                               stream.get("width"), stream.get("height"),
                               stream.get("nb_read_frames")) ==
                              ("av1", "Main", 1280, 720, str(FRAMES)),
            "packet_timestamps": len(pts) == FRAMES and
                                 all(b > a for a, b in zip(pts, pts[1:])) and
                                 (1.8 <= pts[-1] - pts[0] <= 2.2 if args.lock_30fps
                                  else 1.5 <= pts[-1] - pts[0] <= 10.0),
            "dav1d_complete": decoded.returncode == 0 and
                              len(frame_hashes) == FRAMES,
            "libaom_complete": decoded_aom.returncode == 0 and
                               aom_frames == FRAMES,
            "varying_camera_frames": len(set(frame_hashes)) > FRAMES // 2,
        }
        report = {"captured_at": datetime.now(timezone.utc).isoformat(),
                  "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                  "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
                  "driver": run(["/usr/bin/nvidia-smi", "--query-gpu=driver_version",
                                 "--format=csv,noheader"]).stdout.strip(),
                  "ffmpeg_sha256": digest("/usr/bin/ffmpeg"),
                  "aomdec_sha256": digest("/usr/bin/aomdec"),
                  "camera": CAMERA, "requested_frames": FRAMES,
                  "encode_wall_seconds_including_camera_open": round(encode_wall, 3),
                  "input_frames": input_frames, "output_frames": output_frames,
                  "stream": stream, "packet_pts_span_s": round(pts[-1] - pts[0], 3)
                  if pts else None, "bitstream_bytes": bitstream.stat().st_size,
                  "bitstream_sha256": digest(bitstream),
                  "dav1d_frames": len(frame_hashes), "libaom_frames": aom_frames,
                  "distinct_decoded_frame_hashes": len(set(frame_hashes)),
                  "checks": checks, "pass": all(checks.values()),
                  "camera_pixels_or_recording_retained": False,
                  "limit": "Default AV1 Vulkan rate control only; explicit bitrate/CQP modes, A/V sync, visual quality and post-resume use remain separate gates."}
    report["camera_dynamic_framerate_control"] = control
    report["checks"]["camera_control_restored"] = control["after"] == control["before"]
    if args.lock_30fps:
        report["checks"]["fixed_30fps_control"] = control["during"] == 0
    report["pass"] = all(report["checks"].values())
    (args.output_dir / "camera-av1-vulkan.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "input": input_frames,
                      "output": output_frames, "dav1d": len(frame_hashes),
                      "libaom": aom_frames, "distinct": len(set(frame_hashes)),
                      "checks": checks}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
