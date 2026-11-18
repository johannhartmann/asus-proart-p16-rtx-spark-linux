# First native kernel38 boot and media checks

Machine: ASUS ProArt P16 H7607BA, NVIDIA RTX Spark N1X. The first native
`7.2.8-38-rtx-spark-npu` boot has ID
`806fab11-2c93-426d-805b-8a82426047b8` and used the direct, one-time
UEFI `Boot0003` entry. The installed `linux-p16-platform-38` and matching
driver package are `7.2.8-38`; the active NVIDIA kernel and userspace stack
is `615.78.08`. Limine still defaults to kernel36 and permanent UEFI
BootOrder remains `0002,0001,2001,2002,2003`.

The GPU initialized and drove the internal 3840×2400/120 Hz panel and an
external 3840×2160/30 Hz display. All 13 installed kernel38 production
modules matched their package hashes; header and driver `pacman -Qkk` checks
reported zero altered files. Lockdep remained active (`debug_locks: 1`). The
boot journal contained no kernel `WARNING`, `BUG`, KASAN, DMA mapping warning,
NVIDIA Xid or IOMMU fault. These are first-boot observations, not a physical
resume result.

The [native UVC result](kernel38-uvc-native-20261118.json) captured 60 RGB
frames at 720p/30, 60 RGB frames at 1080p/30 and 30 IR frames at 360p/15.
The pinned UVC fix capped the internal RGB URBs at `22 × 2,940 = 64,680`
bytes, rounded to the 65,536-byte DMA limit. IR used 32 × 1,176 bytes,
rounded to 40,960. No new DMA or other kernel warning occurred during those
captures. A separate [external StreamCam check](kernel38-uvc-streamcam-native-20261118.json)
captured 60 MJPEG frames at 1080p/30 on USB host `NVDA8000:00` without a new
kernel warning. That check ran with UVC trace disabled, so the exact external
URB allocation is still unmeasured on kernel38. Post-resume capture is a
separate gate.

The [installed NVENC check](n1x-media-20261118/installed-nvenc-kernel38.json)
again failed H.264, HEVC and AV1 at session open with error 21 on the matched
615 stack. The [120-second NVOFA test](n1x-media-20261118/nvof-120s-kernel38.md)
processed every captured adjacent pair and exported 7,169 decodable frames,
but the camera source had 3,585 rather than 3,600 frames. The
[camera-cadence investigation](n1x-media-20261118/camera-cadence-kernel38.md)
found strong exposure-rate effects and a smooth 3,600-frame fixed-rate Vulkan
output with 16 FFmpeg output-rate drops. A direct 3,600-buffer V4L2 run had
continuous sensor sequence numbers and timestamps under fixed exposure;
a separate 3,600-frame MJPEG decode passed without payload errors. FFmpeg's
passthrough Null muxer still reported non-increasing DTS values. End-to-end
losslessness and clean application timestamps remain open.

## Audio boot-profile issue

This first kernel38 UKI omitted the known-good kernel36 DSP parameters.
`sof-audio-acpi-mt8901` claimed the audio DSP platform device instead of
`n1x_adsp`, so the full platform verification failed at the missing
`asoc_ready` node. NPU task/queue, SCP, Pluton, ALS and firmware checks in
that verification did pass. The absence of the five DSP flags and the SOF
blacklist explains the binding difference; audio playback on this boot is
**not qualified**.

The separate `p16-adsp-boot-policy 0.1.0-1` package installs the normal-boot
Limine command-line drop-in. Only the kernel38 UKI was rebuilt after its
installation. That new image requires offline verification and then one
native boot with audio and display checks; its staging does not retroactively
qualify this boot. No additional reboot or physical suspend occurred while
these media tests were performed.

The next boot is deferred until the rebuilt UKI's DSP command line and full
platform payload check pass, the media package and both UVC hosts have been
checked on this running boot, and the rollback entry remains intact. One
native session can then cover audio route, GPU/display, camera, NVENC and an
attended physical suspend/resume together. Results from that session must
still be recorded separately by device and application.
