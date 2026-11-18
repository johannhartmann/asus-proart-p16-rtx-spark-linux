#!/usr/bin/env python3
"""Bounded N1X codec and optional P16 camera probes with retained logs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


CODECS = ("h264", "hevc", "av1")
VULKAN_EXTENSION = {"h264": "h264", "hevc": "h265", "av1": "av1"}


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def output_line(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=10, check=False)
        return (result.stdout or result.stderr).splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return None


def file_hash(path):
    executable = shutil.which(path)
    if executable is None:
        return None
    digest = hashlib.sha256()
    with open(executable, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command(args, label, evidence, *, env=None, timeout=45):
    result = subprocess.run(
        args, capture_output=True, text=True, errors="replace", timeout=timeout,
        env={**os.environ, **(env or {})}, check=False,
    )
    log = evidence / f"{label}.log"
    content = (
        "$ " + " ".join(args) + "\n\nstdout:\n" + result.stdout
        + "\nstderr:\n" + result.stderr
    )
    log.write_text("\n".join(line.rstrip() for line in content.splitlines()) + "\n")
    return result


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def probe_stream(ffprobe, source, expected_codec, expected_frames, evidence, label):
    result = command(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,width,height,nb_read_frames",
         "-of", "json", str(source)], f"{label}-probe", evidence,
    )
    require(result.returncode == 0, f"{label}: ffprobe failed")
    streams = json.loads(result.stdout).get("streams", [])
    require(len(streams) == 1, f"{label}: expected one video stream")
    stream = streams[0]
    require(stream.get("codec_name") == expected_codec,
            f"{label}: codec {stream.get('codec_name')} != {expected_codec}")
    require(int(stream.get("nb_read_frames", 0)) == expected_frames,
            f"{label}: incomplete frame count {stream.get('nb_read_frames')}")
    require((stream.get("width"), stream.get("height")) == (320, 180),
            f"{label}: unexpected dimensions")
    return stream


def record(results, name, action):
    try:
        data = action()
        results[name] = {"status": "pass", **data}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        results[name] = {"status": "fail", "reason": str(exc)}


def vulkan_encode(ffmpeg, ffprobe, codec, work, evidence):
    label = f"vulkan-{codec}"
    output = work / f"{label}.mkv"
    result = command(
        [ffmpeg, "-hide_banner", "-loglevel", "verbose",
         "-init_hw_device", "vulkan=vk:0", "-filter_hw_device", "vk",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
         "-frames:v", "30", "-vf", "format=nv12,hwupload",
         "-c:v", f"{codec}_vulkan", "-y", str(output)], label, evidence,
    )
    require(result.returncode == 0, f"{label}: FFmpeg exited {result.returncode}")
    require("Device 0 selected: NVIDIA RTX Spark N1X" in result.stderr,
            f"{label}: N1X GPU selection not logged")
    require(f"VK_KHR_video_encode_{VULKAN_EXTENSION[codec]}" in result.stderr,
            f"{label}: Vulkan Video encode extension not logged")
    stream = probe_stream(ffprobe, output, codec, 30, evidence, label)
    decoded = command(
        [ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(output),
         "-frames:v", "30", "-f", "null", "-"], f"{label}-decode", evidence,
    )
    require(decoded.returncode == 0 and re.search(r"frame=\s*30\b", decoded.stderr),
            f"{label}: independent decode did not complete 30 frames")
    return {"stream": stream, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size,
            "hardware_evidence": "N1X Vulkan device and codec encode extension logged"}


def vulkan_10bit_roundtrip(ffmpeg, ffprobe, codec, work, evidence):
    label = f"vulkan-{codec}-10bit"
    output = work / f"{label}.mkv"
    result = command(
        [ffmpeg, "-hide_banner", "-loglevel", "verbose",
         "-init_hw_device", "vulkan=vk:0", "-filter_hw_device", "vk",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
         "-frames:v", "30", "-vf", "format=p010le,hwupload",
         "-c:v", f"{codec}_vulkan", "-y", str(output)], label, evidence,
    )
    require(result.returncode == 0, f"{label}: FFmpeg exited {result.returncode}")
    require("Device 0 selected: NVIDIA RTX Spark N1X" in result.stderr and
            f"VK_KHR_video_encode_{VULKAN_EXTENSION[codec]}" in result.stderr,
            f"{label}: N1X Vulkan encode path not logged")
    probe = command(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames",
         "-of", "json", str(output)], f"{label}-probe", evidence,
    )
    require(probe.returncode == 0, f"{label}: ffprobe failed")
    stream = json.loads(probe.stdout)["streams"][0]
    require(stream.get("codec_name") == codec and
            stream.get("pix_fmt") == "yuv420p10le" and
            stream.get("nb_read_frames") == "30" and
            (stream.get("width"), stream.get("height")) == (320, 180),
            f"{label}: wrong output stream {stream}")
    decoded = command(
        [ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(output),
         "-frames:v", "30", "-f", "null", "-"],
        f"{label}-decode", evidence,
    )
    require(decoded.returncode == 0 and re.search(r"frame=\s*30\b", decoded.stderr),
            f"{label}: independent software decode failed")
    vaapi = vaapi_decode_file(ffmpeg, codec, output, evidence,
                              f"vaapi-{codec}-10bit")
    return {"stream": stream, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size, "vaapi_decode": vaapi,
            "hardware_evidence": "N1X Vulkan encode extension and NVDEC VA-API frames logged"}


def vaapi_decode_file(ffmpeg, codec, source, evidence, label=None):
    label = label or f"vaapi-{codec}"
    result = command(
        [ffmpeg, "-hide_banner", "-loglevel", "verbose", "-hwaccel", "vaapi",
         "-hwaccel_device", "/dev/dri/renderD128", "-hwaccel_output_format", "vaapi",
         "-i", str(source), "-frames:v", "30", "-f", "null", "-"],
        label, evidence,
        env={"LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"},
    )
    require(result.returncode == 0, f"{label}: FFmpeg exited {result.returncode}")
    require("VA-API NVDEC driver [direct backend]" in result.stderr,
            f"{label}: NVIDIA VA-API driver not selected")
    require("pixfmt:vaapi" in result.stderr or "pix_fmt: vaapi" in result.stderr,
            f"{label}: VA-API frame surfaces not observed")
    require(re.search(r"frame=\s*30\b", result.stderr),
            f"{label}: incomplete decode")
    return {"frames": 30, "codec": codec,
            "hardware_evidence": "NVDEC direct backend and VA-API frames logged"}


def vaapi_decode(ffmpeg, ffprobe, work, evidence):
    source = work / "software-h264.mkv"
    generated = command(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x180:rate=10", "-frames:v", "30",
         "-c:v", "libx264", "-y", str(source)], "vaapi-source", evidence,
    )
    require(generated.returncode == 0, "H.264 fixture generation failed")
    probe_stream(ffprobe, source, "h264", 30, evidence, "vaapi-source")
    result = command(
        [ffmpeg, "-hide_banner", "-loglevel", "verbose", "-hwaccel", "vaapi",
         "-hwaccel_device", "/dev/dri/renderD128", "-hwaccel_output_format", "vaapi",
         "-i", str(source), "-frames:v", "30", "-f", "null", "-"],
        "vaapi-h264", evidence,
        env={"LIBVA_DRIVER_NAME": "nvidia", "NVD_BACKEND": "direct"},
    )
    require(result.returncode == 0, f"VA-API decode exited {result.returncode}")
    require("VA-API NVDEC driver [direct backend]" in result.stderr,
            "NVIDIA NVDEC VA-API driver not selected")
    require("pix_fmt: vaapi" in result.stderr,
            "hardware frame format not observed")
    require(re.search(r"frame=\s*30\b", result.stderr), "incomplete decode")
    control = command(
        [ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(source),
         "-frames:v", "30", "-f", "null", "-"], "software-h264-control", evidence,
    )
    require(control.returncode == 0 and re.search(r"frame=\s*30\b", control.stderr),
            "software control failed")
    return {"frames": 30, "codec": "h264", "hardware_evidence": "NVDEC direct backend and VA-API frames logged"}


def camera(ffmpeg, path, pixfmt, size, rate, frames, evidence, label):
    result = command(
        [ffmpeg, "-hide_banner", "-loglevel", "info", "-f", "v4l2",
         "-input_format", pixfmt, "-video_size", size, "-framerate", str(rate),
         "-i", path, "-frames:v", str(frames),
         "-vf", "signalstats,metadata=print", "-f", "null", "-"],
        label, evidence, timeout=20,
    )
    require(result.returncode == 0, f"{label}: capture exited {result.returncode}")
    require(re.search(rf"frame=\s*{frames}\b", result.stderr),
            f"{label}: incomplete capture")
    yavg = [float(value) for value in
            re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", result.stderr)]
    ymin = [int(value) for value in
            re.findall(r"lavfi\.signalstats\.YMIN=([0-9]+)", result.stderr)]
    ymax = [int(value) for value in
            re.findall(r"lavfi\.signalstats\.YMAX=([0-9]+)", result.stderr)]
    require(len(yavg) == frames, f"{label}: missing frame statistics")
    require(any(high > low for low, high in zip(ymin, ymax)),
            f"{label}: no pixel variation")
    return {"device": path, "frames": frames, "format": pixfmt,
            "size": size, "rate": rate, "yavg_min": min(yavg),
            "yavg_max": max(yavg), "pixel_range": [min(ymin), max(ymax)],
            "note": "Frame statistics are not image-quality or privacy qualification"}


def camera_vulkan_record(ffmpeg, ffprobe, work, evidence):
    output = work / "p16-rgb-vulkan-h264.mkv"
    label = "camera-vulkan-h264"
    encoded = command(
        [ffmpeg, "-hide_banner", "-loglevel", "verbose",
         "-init_hw_device", "vulkan=vk:0", "-filter_hw_device", "vk",
         "-f", "v4l2", "-input_format", "mjpeg", "-video_size", "1280x720",
         "-framerate", "30", "-i", "/dev/video0", "-frames:v", "60",
         "-vf", "format=nv12,hwupload", "-c:v", "h264_vulkan",
         "-y", str(output)], label, evidence, timeout=30,
    )
    require(encoded.returncode == 0, f"camera Vulkan encode exited {encoded.returncode}")
    require("Device 0 selected: NVIDIA RTX Spark N1X" in encoded.stderr and
            "VK_KHR_video_encode_h264" in encoded.stderr,
            "N1X Vulkan Video encoder not selected")
    probe = command(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_read_frames",
         "-of", "json", str(output)], f"{label}-probe", evidence,
    )
    require(probe.returncode == 0, "camera Vulkan recording ffprobe failed")
    stream = json.loads(probe.stdout)["streams"][0]
    require(stream.get("codec_name") == "h264" and
            (stream.get("width"), stream.get("height")) == (1280, 720) and
            stream.get("avg_frame_rate") == "30/1" and
            stream.get("nb_read_frames") == "60", f"camera output invalid: {stream}")
    decoded = command(
        [ffmpeg, "-hide_banner", "-loglevel", "info", "-i", str(output),
         "-frames:v", "60", "-vf", "signalstats,metadata=print",
         "-f", "null", "-"], f"{label}-decode", evidence,
    )
    require(decoded.returncode == 0 and re.search(r"frame=\s*60\b", decoded.stderr),
            "camera Vulkan recording failed independent decode")
    means = [float(value) for value in
             re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", decoded.stderr)]
    require(len(means) == 60 and max(means) - min(means) > 1,
            "camera recording did not contain 60 varying frames")
    return {"stream": stream, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size, "mean_min": min(means),
            "mean_max": max(means),
            "hardware_evidence": "Live V4L2 camera encoded by N1X Vulkan Video H.264"}


def nvenc_candidate(ffmpeg, evidence):
    result = command(
        [ffmpeg, "-hide_banner", "-loglevel", "verbose", "-f", "lavfi",
         "-i", "testsrc2=size=320x180:rate=10", "-frames:v", "10",
         "-c:v", "h264_nvenc", "-f", "null", "-"],
        "nvenc-h264", evidence,
    )
    require(result.returncode == 0 and re.search(r"frame=\s*10\b", result.stderr),
            f"NVENC failed (exit {result.returncode}); see nvenc-h264.log")
    return {"frames": 10, "hardware_evidence": "NVENC session and frames completed"}


def cuvid_candidate(ffmpeg, codec, source, evidence, label):
    result = command(
        [ffmpeg, "-hide_banner", "-loglevel", "verbose",
         "-c:v", f"{codec}_cuvid", "-i", str(source),
         "-frames:v", "30", "-f", "null", "-"], label, evidence,
    )
    require(result.returncode == 0, f"{label}: CUVID exited {result.returncode}")
    require(f"{codec}_cuvid" in result.stderr and
            re.search(r"frame=\s*30\b", result.stderr),
            f"{label}: decoder selection or frame count missing")
    return {"frames": 30, "codec": codec,
            "hardware_evidence": f"{codec}_cuvid decoder selected and 30 frames decoded"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--camera", action="store_true", help="capture P16 cameras to /dev/null")
    parser.add_argument("--camera-vulkan-record", action="store_true",
                        help="record 60 live P16 RGB frames through Vulkan Video into a temporary file")
    parser.add_argument("--nvenc-candidate", help="also test this isolated FFmpeg NVENC binary")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": {"product": read("/sys/class/dmi/id/product_name"),
                 "bios": read("/sys/class/dmi/id/bios_version"),
                 "kernel": read("/proc/sys/kernel/osrelease")},
        "software": {
            "nvidia": output_line(["nvidia-smi", "--query-gpu=name,driver_version",
                                   "--format=csv,noheader"]),
            "ffmpeg": output_line([args.ffmpeg, "-version"]),
            "ffmpeg_sha256": file_hash(args.ffmpeg),
            "ffmpeg_package": output_line(["pacman", "-Q", "ffmpeg"]),
            "libva_nvidia_package": output_line(["pacman", "-Q", "libva-nvidia-driver"]),
            "x265_package": output_line(["pacman", "-Q", "x265"]),
            "nvenc_candidate_sha256": file_hash(args.nvenc_candidate)
            if args.nvenc_candidate else None,
        },
        "results": {}, "limits": [
            "This command-line run does not test browser, OBS, visible playback, reboot or physical resume; application tests need separate evidence",
            "Vulkan Video encode does not prove NVENC API session availability",
            "Camera frame statistics do not establish image quality or face authentication",
        ],
    }
    with tempfile.TemporaryDirectory(prefix="n1x-media-") as temporary:
        work = Path(temporary)
        record(report["results"], "vaapi_h264",
               lambda: vaapi_decode(args.ffmpeg, args.ffprobe, work, args.output_dir))
        for codec in CODECS:
            record(report["results"], f"vulkan_{codec}",
                   lambda codec=codec: vulkan_encode(
                       args.ffmpeg, args.ffprobe, codec, work, args.output_dir))
            if report["results"][f"vulkan_{codec}"]["status"] == "pass":
                record(report["results"], f"vaapi_{codec}_from_vulkan",
                       lambda codec=codec: vaapi_decode_file(
                           args.ffmpeg, codec, work / f"vulkan-{codec}.mkv",
                           args.output_dir))
        for codec in ("hevc", "av1"):
            record(report["results"], f"vulkan_{codec}_10bit_roundtrip",
                   lambda codec=codec: vulkan_10bit_roundtrip(
                       args.ffmpeg, args.ffprobe, codec, work, args.output_dir))
        if args.camera:
            record(report["results"], "p16_rgb",
                   lambda: camera(args.ffmpeg, "/dev/video0", "mjpeg", "1280x720",
                                  30, 30, args.output_dir, "p16-rgb"))
            record(report["results"], "p16_ir",
                   lambda: camera(args.ffmpeg, "/dev/video2", "gray", "360x360",
                                  15, 15, args.output_dir, "p16-ir"))
        if args.camera_vulkan_record:
            record(report["results"], "p16_rgb_vulkan_record",
                   lambda: camera_vulkan_record(args.ffmpeg, args.ffprobe,
                                                work, args.output_dir))
        if args.nvenc_candidate:
            for codec in CODECS:
                if report["results"].get(f"vulkan_{codec}", {}).get("status") == "pass":
                    record(report["results"], f"cuvid_{codec}",
                           lambda codec=codec: cuvid_candidate(
                               args.nvenc_candidate, codec,
                               work / f"vulkan-{codec}.mkv", args.output_dir,
                               f"cuvid-{codec}"))
            for codec in ("hevc", "av1"):
                if report["results"].get(f"vulkan_{codec}_10bit_roundtrip", {}).get("status") == "pass":
                    record(report["results"], f"cuvid_{codec}_10bit",
                           lambda codec=codec: cuvid_candidate(
                               args.nvenc_candidate, codec,
                               work / f"vulkan-{codec}-10bit.mkv", args.output_dir,
                               f"cuvid-{codec}-10bit"))
            record(report["results"], "nvenc_h264",
                   lambda: nvenc_candidate(args.nvenc_candidate, args.output_dir))
    path = args.output_dir / "result.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(path)
    for name, result in report["results"].items():
        print(f"{name}: {result['status']}")
    return int(any(item["status"] == "fail" for item in report["results"].values()))


if __name__ == "__main__":
    sys.exit(main())
