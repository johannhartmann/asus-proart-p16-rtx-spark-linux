# P16 camera privacy controls

The owner reports that this H7607BA has no physical camera shutter. On 18
November 2026, the internal RGB camera at `/dev/video0` exposed the UVC
`privacy` control as read-only and set to 0. A normal user could set the
writable `brightness` control to its existing value, but an attempt to set
`privacy=1` failed with `Permission denied`. A readback still returned 0.
The camera then supplied 30 live 1280×720 MJPEG frames; only luma statistics
were saved. [`camera-privacy-control.json`](camera-privacy-control.json)
contains the exact result. This is evidence that the UVC privacy control
cannot provide a software camera off switch on the tested firmware, not proof
of an undocumented electronic shutter or LED state.

The installed `p16-camera-privacy` command uses the Linux USB core's
`authorized` attribute on the internal camera's USB device. Its privileged
helper verifies ACPI parent `NVDA8001:00` and USB ID `636e:0bdb` before a
write, and the user-facing command uses graphical Polkit authentication.
`status` is read-only; `off` removes both RGB and IR V4L2 nodes, and `on`
restores them. `self-test` is a bounded off/on transition with restoration in
`finally`. This is a software access control, not a hardware shutter. USB
authorization can reset after reboot or re-enumeration.

The [installed self-test](camera-privacy-switch.json) passed through the
`pkexec`/Polkit path: all four internal V4L2 nodes disappeared with
`authorized=0` and returned with `authorized=1`. The final state was enabled.
Afterward, an unprivileged [30-frame V4L2 capture](camera-privacy-after-switch.json)
and a [30-frame Chromium WebRTC preview](browser-camera-after-privacy-switch.json)
both passed. The camera's USB HID sensor interface also re-enumerated with
the camera; the switch therefore controls the whole internal USB camera
device rather than only its RGB stream. The two source files match the
installed command hashes, and `pacman -Qk` reports 18 package files with none
missing. No camera pixels were retained.
