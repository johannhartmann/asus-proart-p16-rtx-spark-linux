#!/usr/bin/env python3
"""Request Camera portal access from GTK and count PipeWire buffers."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

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
                stream = subprocess.run(
                    ["gst-launch-1.0", "-v", "pipewiresrc", f"fd={fd}",
                     "num-buffers=30", "!", "identity", "silent=false", "!",
                     "fakesink", "sync=false"],
                    pass_fds=(fd,), capture_output=True, text=True, check=False,
                    timeout=20)
            finally:
                os.close(fd)
            result["gstreamer_exit_code"] = stream.returncode
            result["pipewire_buffers"] = len(re.findall(
                r"last-message = chain", stream.stdout))
            result["stream_caps"] = list(dict.fromkeys(re.findall(
                r"caps = ([^\n]+)", stream.stdout)))[:4]
            result["stream_errors"] = [
                line for line in stream.stderr.splitlines()
                if "ERROR:" in line or "error:" in line]
            if (stream.returncode != 0 or result["pipewire_buffers"] != 30 or
                    "Got EOS" not in stream.stdout):
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
