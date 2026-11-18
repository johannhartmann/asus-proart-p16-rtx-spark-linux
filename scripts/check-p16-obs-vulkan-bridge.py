#!/usr/bin/env python3
"""Independently verify an OBS→NUT→Vulkan Video H.264/AAC recording."""

import argparse
import array
import json
from pathlib import Path
import subprocess


def run(command, *, text=True):
    return subprocess.run(command, capture_output=True, text=text, check=True, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--minimum-frames", type=int, default=180)
    parser.add_argument("--tone-hz", type=float, default=997)
    args = parser.parse_args()

    probe = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                            "-show_packets", "-of", "json", str(args.recording)]).stdout)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", str(args.recording),
                             "-f", "null", "-"], capture_output=True, text=True,
                            check=False, timeout=120)
    hashes = run(["ffmpeg", "-v", "error", "-i", str(args.recording),
                  "-map", "0:v:0", "-vf", "scale=16:9,format=gray",
                  "-f", "framemd5", "-"]).stdout
    frame_hashes = [line.rsplit(",", 1)[-1].strip() for line in hashes.splitlines()
                    if line and not line.startswith("#")]
    timing = {}
    for packet in probe["packets"]:
        if "pts_time" not in packet:
            continue
        index = packet["stream_index"]
        start = float(packet["pts_time"])
        end = start + float(packet.get("duration_time", 0))
        entry = timing.setdefault(index, {"start": start, "end": end, "packets": 0})
        entry["start"] = min(entry["start"], start)
        entry["end"] = max(entry["end"], end)
        entry["packets"] += 1
    pcm = run(["ffmpeg", "-v", "error", "-i", str(args.recording), "-map", "0:a:0",
               "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], text=False).stdout
    samples = array.array("f")
    samples.frombytes(pcm)
    middle = samples[48000:min(len(samples), 5 * 48000)]
    crossings = sum((a >= 0) != (b >= 0) for a, b in zip(middle, middle[1:]))
    tone_hz = crossings / (2 * len(middle) / 48000) if middle else 0
    rms = (sum(value * value for value in middle) / len(middle)) ** 0.5 if middle else 0
    av_end_delta_ms = (timing[video["index"]]["end"] - timing[audio["index"]]["end"]) * 1000
    report = {
        "recording": str(args.recording),
        "video": {"codec": video["codec_name"], "width": video["width"],
                  "height": video["height"], "encoder": video.get("tags", {}).get("ENCODER"),
                  "frames": len(frame_hashes), "distinct_downscaled_frames": len(set(frame_hashes))},
        "audio": {"codec": audio["codec_name"], "sample_rate": audio["sample_rate"],
                  "channels": audio["channels"], "tone_hz_estimate": round(tone_hz, 3),
                  "middle_rms": round(rms, 5)},
        "packet_timing": timing,
        "av_end_delta_ms": round(av_end_delta_ms, 3),
        "independent_decode_exit_code": decode.returncode,
        "pixels_or_audio_retained": False,
    }
    report["pass"] = (decode.returncode == 0 and video["codec_name"] == "h264" and
                      video["width"] == 1280 and video["height"] == 720 and
                      "h264_vulkan" in (report["video"]["encoder"] or "") and
                      len(frame_hashes) >= args.minimum_frames and
                      len(set(frame_hashes)) >= args.minimum_frames and
                      audio["codec_name"] == "aac" and int(audio["sample_rate"]) == 48000 and
                      abs(tone_hz - args.tone_hz) <= 5 and rms >= 0.02 and
                      abs(av_end_delta_ms) <= 50)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
