# IR preview close behavior on native kernel38

The internal IR node is the P16's separate 360×360 GREY UVC stream. All
checks below ran on boot `806fab11-2c93-426d-805b-8a82426047b8` with
`7.2.8-38-rtx-spark-npu`, mpv 0.41.0 and FFmpeg 9.0.2. No IR pixels or
recording were retained.

| Consumer and close path | Captured/advanced frames | V4L2 owned-buffer warning | QBUF bad-fd lines | Reopen |
| --- | ---: | --- | ---: | --- |
| [mpv Wayland/Vulkan, ordinary IPC quit](ir-mpv-preview-kernel38.json) | 1.599 s of advancing playback | Yes | 0 | Pass |
| [mpv direct demux, IPC quit](ir-mpv-preview-direct-demux-kernel38.json) | advancing playback | Yes | 2 | Pass |
| [mpv Wayland SHM, IPC quit](ir-mpv-preview-wlshm-kernel38.json) | advancing playback | Yes | 0 | Pass |
| [mpv Wayland/Vulkan, explicit IPC stop then quit](ir-mpv-preview-stop-first-kernel38.json) | 1.599 s of advancing playback | Yes | 0 | Pass |
| [`v4l2-ctl` mmap to `/dev/null`](ir-v4l2-close-controls-kernel38.json) | 45 frame markers | No | 0 | Next consumer opens |
| [FFmpeg V4L2 to null](ir-v4l2-close-controls-kernel38.json) | 45 frames | No | 0 | Next consumer opens |
| [FFmpeg V4L2 to null, interrupted with SIGINT](ir-v4l2-close-controls-kernel38.json) | 46 frames | No | 0 | N/A |

The [control script](../../../scripts/check-p16-ir-close-controls.py) runs
the last three checks sequentially because the camera is exclusive while
streaming. FFmpeg's SIGINT exit code is 255, but it reports normal signal
handling and does not emit the buffer warning. The bounded controls exit 0.
The mpv preview test uses the installed Wayland renderer, receives the actual
GREY format and advancing timestamps, and reopens the device afterward.

The warning is therefore reproducible on mpv's live-stream close path on
this boot; the controls do not reproduce it. Renderer choice and an explicit
`stop` IPC call do not clear it. This evidence does not identify a kernel
fault or prove one is absent. Warning-free mpv shutdown remains open, while
normal IR preview and subsequent V4L2 use pass. GStreamer's `v4l2src` is
not installed here (`gst-plugins-good` is absent); the existing installed
GStreamer/Vulkan recorder obtains RGB camera frames through its FFmpeg bridge.
