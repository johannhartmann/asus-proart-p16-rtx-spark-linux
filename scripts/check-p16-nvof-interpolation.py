#!/usr/bin/env python3
"""Qualify NVOFA midpoint export, Vulkan encoding and desktop playback."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time


def run(args, *, data=None, env=None):
    return subprocess.run(args, input=data, capture_output=True, check=True, env=env)


def probe(path, selector):
    return json.loads(run(["/usr/bin/ffprobe", "-v", "error", "-select_streams", selector,
                           "-count_frames", "-show_entries",
                           "stream=codec_name,width,height,avg_frame_rate,nb_read_frames",
                           "-of", "json", str(path)]).stdout)["streams"]


def end_time(path, selector):
    packets = json.loads(run(["/usr/bin/ffprobe", "-v", "error", "-select_streams", selector,
                              "-show_packets", "-show_entries", "packet=pts_time,duration_time",
                              "-of", "json", str(path)]).stdout)["packets"]
    return max(float(p["pts_time"]) + float(p.get("duration_time", 0)) for p in packets)


def shifted(frame, width, height, dx):
    out = bytearray(len(frame))
    for y in range(height):
        first = y * width * 3
        out[first + dx * 3:first + width * 3] = frame[first:first + (width - dx) * 3]
    return bytes(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--analyzer", default="/usr/bin/p16-nvof-analyze")
    parser.add_argument("--wrapper", default="/usr/bin/p16-interpolate-video")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    width, height = 320, 180
    rng = random.Random(42)
    first = bytes(rng.randrange(256) for _ in range(width * height * 3))
    last = shifted(first, width, height, 8)
    expected = shifted(first, width, height, 4)
    control = run([args.analyzer, "--interpolate", str(width), str(height), "1"],
                  data=first + last)
    frame_bytes = len(first)
    frames = [control.stdout[i:i + frame_bytes]
              for i in range(0, len(control.stdout), frame_bytes)]
    if len(frames) != 3:
        raise RuntimeError("NVOFA produced the wrong controlled frame count")
    interior = [(y * width + x) * 3 + c
                for y in range(16, height - 16)
                for x in range(16, width - 16)
                for c in range(3)]
    mse = lambda image: sum((image[i] - expected[i]) ** 2 for i in interior) / len(interior)
    crossfade = bytes((a + b) // 2 for a, b in zip(first, last))
    full_width, full_height = 1280, 720
    full_rng = random.Random(43)
    full_first = bytes(full_rng.randrange(256) for _ in range(full_width * full_height * 3))
    full_last = shifted(full_first, full_width, full_height, 8)
    full_control = run([args.analyzer, "--interpolate", str(full_width),
                        str(full_height), "1"], data=full_first + full_last)
    full_middle = full_control.stdout[len(full_first):2 * len(full_first)]
    full_target = shifted(full_first, full_width, full_height, 4)
    full_indices = [(y * full_width + x) * 3 + c
                    for y in range(16, full_height - 16, 13)
                    for x in range(16, full_width - 16, 13)
                    for c in range(3)]
    full_mse = sum((full_middle[i] - full_target[i]) ** 2 for i in full_indices) / len(full_indices)
    with tempfile.TemporaryDirectory(prefix="p16-nvof-interp-") as temporary:
        root = Path(temporary)
        source = root / "timed-source.mkv"
        av_out = root / "timed-interpolated.mkv"
        camera = root / "camera.mkv"
        camera_out = root / "camera-interpolated.mkv"
        run(["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
             "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", "-y", str(source)])
        env = os.environ.copy()
        env["P16_NVOF_BINARY"] = args.analyzer
        start = time.monotonic()
        av = run([args.wrapper, str(source), str(av_out), "50"], env=env)
        av_elapsed = time.monotonic() - start
        av_video = probe(av_out, "v:0")[0]
        av_audio = probe(av_out, "a:0")[0]
        av_video_end = end_time(av_out, "v:0")
        av_audio_end = end_time(av_out, "a:0")
        run(["/usr/bin/ffmpeg", "-v", "error", "-i", str(av_out), "-f", "null", "-"])
        camera_record = run(["/usr/bin/p16-record-camera-vulkan", "2", str(camera)])
        start = time.monotonic()
        camera_export = run([args.wrapper, str(camera), str(camera_out), "100"], env=env)
        camera_elapsed = time.monotonic() - start
        camera_video = probe(camera_out, "v:0")[0]
        run(["/usr/bin/ffmpeg", "-v", "error", "-i", str(camera_out), "-f", "null", "-"])
        player_log = root / "player.log"
        player = run(["/usr/bin/p16-video-play", str(camera_out), "--no-config", "--no-audio",
                      "--msg-level=all=info", f"--log-file={player_log}"])
        playback = player_log.read_text(errors="replace")
        camera_log = (camera_record.stdout + camera_record.stderr).decode(errors="replace")
        export_log = (camera_export.stdout + camera_export.stderr).decode(errors="replace")
        saved_log = (camera_log + "\n" + export_log).replace(temporary, "$TEMP")
        (args.evidence / "nvof-interpolation-camera.log").write_text(
            "\n".join(line.rstrip() for line in saved_log.splitlines()) + "\n")
        result = {
            "package": run(["/usr/bin/pacman", "-Q", "p16-nvof-tools"]).stdout.decode().strip(),
            "analyzerSha256": hashlib.sha256(Path(args.analyzer).read_bytes()).hexdigest(),
            "wrapperSha256": hashlib.sha256(Path(args.wrapper).read_bytes()).hexdigest(),
            "controlled": {"outputFrames": len(frames), "sourceFramesPreserved":
                           frames[0] == first and frames[2] == last,
                           "midpointMse": mse(frames[1]), "crossfadeMse": mse(crossfade),
                           "fullResolution": {"width": full_width, "height": full_height,
                                              "outputFrames": len(full_control.stdout) // len(full_first),
                                              "sampledMidpointMse": full_mse},
                           "nvofPairsLogged": "nvof_interpolated_pairs=1" in
                           control.stderr.decode(errors="replace")},
            "timedAv": {"video": av_video, "audio": av_audio,
                        "exportElapsedSeconds": round(av_elapsed, 3),
                        "videoEndSeconds": av_video_end, "audioEndSeconds": av_audio_end,
                        "endOffsetSeconds": abs(av_video_end - av_audio_end),
                        "nvofPairsLogged": "nvof_interpolated_pairs=47" in
                        (av.stdout + av.stderr).decode(errors="replace"),
                        "vulkanEncoderLogged": "h264_vulkan" in
                        (av.stdout + av.stderr).decode(errors="replace")},
            "liveCamera": {"sourceFrames": probe(camera, "v:0")[0]["nb_read_frames"],
                           "exportElapsedSeconds": round(camera_elapsed, 3),
                           "output": camera_video,
                           "nvofPairsLogged": "nvof_interpolated_pairs=59" in export_log,
                           "vulkanEncoderLogged": "h264_vulkan" in export_log,
                           "mpvExit": player.returncode,
                           "mpvVaapiDecode": "Using hardware decoding (vaapi)." in playback,
                           "mpvVulkanRenderer": "VO: [gpu-next] 1280x720 vaapi[nv12]" in playback,
                           "mpvEof": "Exiting... (End of file)" in playback},
            "cameraPixelsRetained": False}
    c, a, live = result["controlled"], result["timedAv"], result["liveCamera"]
    result["pass"] = (c["sourceFramesPreserved"] and c["nvofPairsLogged"] and
                      c["midpointMse"] < 1 and c["crossfadeMse"] > 1000 and
                      c["fullResolution"]["outputFrames"] == 3 and
                      c["fullResolution"]["sampledMidpointMse"] < 1 and
                      a["video"]["codec_name"] == "h264" and
                      a["video"]["avg_frame_rate"] == "48/1" and
                      a["video"]["nb_read_frames"] == "95" and
                      a["audio"]["codec_name"] == "aac" and
                      a["endOffsetSeconds"] < 0.1 and a["nvofPairsLogged"] and
                      a["vulkanEncoderLogged"] and live["sourceFrames"] == "60" and
                      live["output"]["avg_frame_rate"] == "60/1" and
                      live["output"]["width"] == 1280 and
                      live["output"]["height"] == 720 and
                      live["output"]["nb_read_frames"] == "119" and
                      all(live[key] for key in ("nvofPairsLogged", "vulkanEncoderLogged",
                                                "mpvVaapiDecode", "mpvVulkanRenderer", "mpvEof")))
    (args.evidence / "nvof-interpolation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pass": result["pass"], "midpointMse": c["midpointMse"],
                      "crossfadeMse": c["crossfadeMse"], "cameraOutputFrames":
                      live["output"]["nb_read_frames"]}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
