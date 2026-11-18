#!/usr/bin/env python3
"""Request Camera portal access from GTK and count PipeWire buffers."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Xdp", "1.0")
gi.require_version("XdpGtk4", "1.0")
from gi.repository import Gio, GLib, Gtk, Xdp, XdpGtk4  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    portal = Xdp.Portal.new()
    result = {"camera_present": bool(portal.is_camera_present()),
              "access_granted": False, "pipewire_buffers": 0,
              "retained_camera_pixels": False, "status": "fail"}
    app = Gtk.Application(application_id="io.github.johannhartmann.P16CameraPortalProbe")
    window = None
    parent = None

    def finish():
        if window is not None:
            window.close()
        app.quit()

    def on_timeout():
        result["reason"] = "Camera portal request timed out"
        finish()
        return False

    def on_camera_access(_portal, response, _user_data):
        try:
            result["access_granted"] = bool(portal.access_camera_finish(response))
            if not result["access_granted"]:
                raise RuntimeError("Camera portal access was not granted")
            fd = portal.open_pipewire_remote_for_camera()
            if fd < 0:
                raise RuntimeError("Camera portal did not provide a PipeWire remote")
            try:
                helper = Path(__file__).with_name("portal-pw-nodes.c")
                compile_cmd = ["cc", "-O2", "-Wall", "-Wextra", "-Werror"]
                compile_cmd += subprocess.check_output(
                    ["pkg-config", "--cflags", "libpipewire-0.3"], text=True).split()
                with tempfile.TemporaryDirectory(prefix="p16-portal-") as temp:
                    binary = str(Path(temp) / "portal-pw-nodes")
                    compile_cmd += [str(helper), "-o", binary]
                    compile_cmd += subprocess.check_output(
                        ["pkg-config", "--libs", "libpipewire-0.3"], text=True).split()
                    subprocess.run(compile_cmd, check=True, capture_output=True, timeout=15)
                    nodes = subprocess.run(
                        [binary, str(fd)], pass_fds=(fd,), capture_output=True,
                        text=True, check=True, timeout=10)
                portal_nodes = [
                    dict(zip(("id", "serial", "name", "media_class", "permissions"),
                             line.split("\t")))
                    for line in nodes.stdout.splitlines()]
                latest_nodes = {node["id"]: node for node in portal_nodes}
                result["portal_video_nodes"] = [
                    node for node in latest_nodes.values()
                    if node["media_class"].startswith("Video/Source")]
                sources = [node for node in result["portal_video_nodes"]
                           if "NVDA8001_00-usb-0_1_1.0" in node["name"]]
                if not sources:
                    raise RuntimeError("Camera portal remote exposed no P16 RGB camera node")
                target = sources[0]["serial"] or sources[0]["name"]
                result["selected_video_node"] = sources[0]
                command = ["gst-launch-1.0", "-v", "pipewiresrc", f"fd={fd}",
                           f"target-object={target}",
                           "stream-properties=props,media.type=(string)Video,"
                           "media.category=(string)Capture,media.role=(string)Camera",
                           "num-buffers=30", "!",
                           "identity", "silent=false", "!", "fakesink", "sync=false"]
                try:
                    stream = subprocess.run(
                        command, pass_fds=(fd,), capture_output=True,
                        text=True, check=False, timeout=20)
                    stdout, stderr = stream.stdout, stream.stderr
                    result["gstreamer_exit_code"] = stream.returncode
                except subprocess.TimeoutExpired as exc:
                    stdout = (exc.stdout or b"").decode(errors="replace")
                    stderr = (exc.stderr or b"").decode(errors="replace")
                    result["gstreamer_timed_out"] = True
            finally:
                os.close(fd)
            result["pipewire_buffers"] = len(re.findall(
                r"last-message = chain", stdout))
            result["stream_caps"] = list(dict.fromkeys(re.findall(
                r"caps = ([^\n]+)", stdout)))[:4]
            result["stream_errors"] = [
                line for line in stderr.splitlines()
                if "ERROR:" in line or "error:" in line]
            sizes = [int(n) for n in re.findall(r"last-message = chain[^\n]*\((\d+) bytes,", stdout)]
            result["buffer_bytes_min"] = min(sizes) if sizes else 0
            result["buffer_bytes_max"] = max(sizes) if sizes else 0
            if (result.get("gstreamer_timed_out") or
                    result.get("gstreamer_exit_code") != 0 or
                    result["pipewire_buffers"] != 30 or "Got EOS" not in stdout):
                result["gstreamer_output_tail"] = stdout[-1200:]
                raise RuntimeError("Portal PipeWire stream did not deliver 30 buffers")
            result["status"] = "pass"
        except (GLib.Error, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            result["reason"] = str(exc)
        finally:
            finish()

    def on_activate(application):
        nonlocal window, parent
        window = Gtk.ApplicationWindow(application=application)
        window.set_title("P16 Camera Portal Test")
        window.set_default_size(320, 100)
        window.set_child(Gtk.Label(label="Testing camera permission and PipeWire capture"))
        window.present()
        parent = XdpGtk4.parent_new_gtk(window)
        portal.access_camera(parent, Xdp.CameraFlags.NONE, None,
                             on_camera_access, None)
        GLib.timeout_add_seconds(90, on_timeout)

    if result["camera_present"]:
        app.connect("activate", on_activate)
        app.run([])
    else:
        result["reason"] = "Camera portal reports no camera"
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
