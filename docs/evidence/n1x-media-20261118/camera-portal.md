# Native GTK camera portal and PipeWire capture

On 18 November 2026, the P16 ran PipeWire 1.6.10, WirePlumber 0.5.18,
`xdg-desktop-portal`, and the Hyprland/GTK portal backends. A native GTK4
application registered as `io.github.johannhartmann.P16CameraPortalProbe`
requested camera access through libportal. The graphical permission dialog
appeared and access was granted. Its `OpenPipeWireRemote` descriptor was passed
to a PipeWire registry client and GStreamer. The client selected the internal
ASUS RGB camera (`/dev/video0`, node name ending `NVDA8001_00-usb-0_1_1.0`).

The first `pipewiresrc` attempts failed with `target not found`, even with the
correct node serial. The missing stream properties were
`media.type=Video`, `media.category=Capture`, and `media.role=Camera`. After
adding them and a full-resolution caps filter, the application captured 30
MJPEG buffers at 1280×720/30 fps and reached EOS. The final run's buffer sizes
ranged from 94,404 to 248,052 bytes.
These sizes establish nonempty input without retaining camera images.
[`camera-portal.json`](camera-portal.json) records the final application result.

The test uses [`check-p16-camera-portal.py`](../../../scripts/check-p16-camera-portal.py)
and its small [PipeWire registry helper](../../../scripts/portal-pw-nodes.c).
The helper compiles with the installed `libpipewire-0.3` development headers.
To reproduce the registered native app identity, create a desktop entry named
`io.github.johannhartmann.P16CameraPortalProbe.desktop` under
`~/.local/share/applications/` with `Exec` pointing at the test script, then
run the script in the graphical session with `GIO_LAUNCHED_DESKTOP_FILE`
pointing to that entry and an `--output` JSON path. Camera access is requested
through libportal; the user handles any graphical permission prompt. The
temporary desktop entry used for qualification was removed afterward.

This qualifies native portal-mediated PipeWire capture. It does not qualify a
sandboxed Flatpak app, permission denial/revocation, or capture after physical
suspend/resume.
