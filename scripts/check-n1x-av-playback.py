#!/usr/bin/env python3
"""Exercise installed P16 hardware playback with audio and interactive controls."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rpc(stream, request_id, command):
    stream.write(json.dumps({"command": command, "request_id": request_id}) + "\n")
    stream.flush()
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError(f"mpv IPC ended during {command}")
        result = json.loads(line)
        if result.get("request_id") == request_id:
            if result.get("error") != "success":
                raise RuntimeError(f"mpv IPC {command}: {result.get('error')}")
            return result.get("data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player", default="/usr/bin/p16-video-play")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / "av-playback-mpv.log"
    report = {"player": str(args.player), "player_sha256": sha256(args.player),
              "kernel": Path("/proc/sys/kernel/osrelease").read_text().strip(),
              "driver": subprocess.check_output(
                  ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                  text=True, timeout=10).strip(),
              "steps": {}, "status": "fail"}

    with tempfile.TemporaryDirectory(prefix="n1x-av-playback-") as directory:
        work = Path(directory)
        fixture = work / "av.mp4"
        fixture_command = ["ffmpeg", "-hide_banner", "-loglevel", "error",
                           "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                           "-t", "24", "-c:v", "libx264", "-preset", "ultrafast",
                           "-crf", "24", "-pix_fmt", "yuv420p", "-c:a", "aac",
                           "-b:a", "96k", "-shortest", "-y", str(fixture)]
        subprocess.run(fixture_command, check=True, capture_output=True, timeout=45)
        report["fixture"] = {"sha256": sha256(fixture), "duration_s": 24,
                             "video": "H.264 640x360 30 fps", "audio": "AAC 48 kHz mono"}
        endpoint = work / "mpv.sock"
        command = [args.player, str(fixture), "--no-config", "--force-window=yes",
                   "--autofit=640x360", "--volume=2", "--input-ipc-server=" + str(endpoint),
                   "--log-file=" + str(log_path), "--msg-level=all=info"]
        with subprocess.Popen(command, stdout=subprocess.DEVNULL,
                              stderr=subprocess.STDOUT) as player:
            try:
                deadline = time.monotonic() + 20
                while not endpoint.exists():
                    if player.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("mpv did not open its IPC socket")
                    time.sleep(0.05)
                client = socket.socket(socket.AF_UNIX)
                client.settimeout(10)
                client.connect(str(endpoint))
                with client, client.makefile("rw") as stream:
                    serial = 0

                    def call(*parts):
                        nonlocal serial
                        serial += 1
                        return rpc(stream, serial, list(parts))

                    def sample(name):
                        deadline = time.monotonic() + 8
                        while True:
                            try:
                                video = call("get_property", "time-pos")
                                audio = call("get_property", "audio-pts")
                                break
                            except RuntimeError:
                                if time.monotonic() >= deadline:
                                    raise
                                time.sleep(0.1)
                        entry = {"video_time_s": video, "audio_time_s": audio,
                                 "av_delta_s": round(audio - video, 4),
                                 "hwdec_current": call("get_property", "hwdec-current"),
                                 "paused": call("get_property", "pause"),
                                 "mistimed_frames": call("get_property", "mistimed-frame-count")}
                        report["steps"][name] = entry
                        return entry

                    time.sleep(3)
                    start = sample("playing")
                    if start["hwdec_current"] != "vaapi" or abs(start["av_delta_s"]) > 0.25:
                        raise RuntimeError("initial hardware decode or A/V clock check failed")
                    call("seek", 10, "absolute")
                    time.sleep(1)
                    forward = sample("forward_seek")
                    if not 10 <= forward["video_time_s"] < 13:
                        raise RuntimeError("forward seek did not land at 10 seconds")
                    call("set_property", "pause", True)
                    paused_at = sample("paused")
                    time.sleep(1)
                    paused_later = sample("paused_after_one_second")
                    if not paused_later["paused"] or abs(
                            paused_later["video_time_s"] - paused_at["video_time_s"]) > 0.07:
                        raise RuntimeError("video clock advanced during pause")
                    call("set_property", "pause", False)
                    time.sleep(1)
                    resumed = sample("resumed")
                    if resumed["paused"] or resumed["video_time_s"] <= paused_later["video_time_s"]:
                        raise RuntimeError("playback did not resume")
                    call("seek", 4, "absolute")
                    time.sleep(1)
                    backward = sample("backward_seek")
                    if not 4 <= backward["video_time_s"] < 7:
                        raise RuntimeError("backward seek did not land at 4 seconds")
                    call("seek", 18, "absolute")
                    time.sleep(1)
                    near_end = sample("near_end")
                    for name in ("forward_seek", "resumed", "backward_seek", "near_end"):
                        item = report["steps"][name]
                        if item["hwdec_current"] != "vaapi" or abs(item["av_delta_s"]) > 0.25:
                            raise RuntimeError(f"{name}: hardware decode or A/V clock check failed")
                    if not 18 <= near_end["video_time_s"] < 21:
                        raise RuntimeError("final seek did not land at 18 seconds")
                    if player.wait(timeout=15) != 0:
                        raise RuntimeError("mpv failed before EOF")
            finally:
                if player.poll() is None:
                    player.terminate()
                    try:
                        player.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        player.kill()
                        player.wait(timeout=3)

    log = log_path.read_text(errors="replace")
    report["checks"] = {
        "hardware_decode": "Using hardware decoding (vaapi)." in log,
        "pipewire_audio": "AO: [pipewire]" in log,
        "vulkan_renderer": re.search(r"VO: \[gpu-next\].*vaapi\[nv12\]", log) is not None,
        "end_of_file": "Exiting... (End of file)" in log,
    }
    if not all(report["checks"].values()):
        raise RuntimeError("mpv log did not confirm VA-API, PipeWire, Vulkan and EOF")
    report["status"] = "pass"
    with gzip.open(str(log_path) + ".gz", "wt") as archived:
        archived.write(log.replace(str(work), "$WORKDIR").replace(str(Path.home()), "$HOME"))
    log_path.unlink()
    (args.output_dir / "av-playback.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "checks": report["checks"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
