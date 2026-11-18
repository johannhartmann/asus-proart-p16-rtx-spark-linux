# FFmpeg Vulkan scaling filter boundary on native kernel 38

On boot `806fab11-2c93-426d-805b-8a82426047b8`, kernel
`7.2.8-38-rtx-spark-npu`, NVIDIA 615.78.08, FFmpeg 9.0.2-2 and libplacebo
7.360.1-7, a one-frame 640×360 → 1280×720 `libplacebo` filter command
selects the NVIDIA RTX Spark N1X Vulkan device but exits 234 before
processing a frame:

```sh
ffmpeg -hide_banner -loglevel error -init_hw_device vulkan=vk:0 \
  -filter_hw_device vk -f lavfi -i testsrc2=size=640x360:rate=30 \
  -vf format=nv12,hwupload,libplacebo=w=1280:h=720,hwdownload,format=nv12 \
  -frames:v 1 -f null -
```

The error is `Error initializing filters` / `Invalid argument`. Replacing
`libplacebo=w=1280:h=720` with `scale_vulkan=w=1280:h=720` in the same command
processes one frame and exits 0. This control proves the Vulkan device and
upload/download chain work; it says nothing about scaling quality.

The unstripped isolated FFmpeg 9.0.2 build provides the cause. GDB stopped at
`libavfilter/vf_libplacebo.c:662`, `copy_pl_queue`, with
`hwctx->queue_flags = 4` (`VK_QUEUE_TRANSFER_BIT`). FFmpeg's code returns
`AVERROR(EINVAL)` there whenever it was compiled with `PL_API_VER < 365`.
The installed libplacebo headers define `PL_API_VER 360`. The caller was
`init_vulkan` → `libplacebo_init`; no frame had been queued. This is an FFmpeg
adapter/library API boundary, not evidence of a failed N1X shader.

The local Arch ARM sync database offers libplacebo 7.387.0-1, but a direct
upgrade is rejected: installed `ffmpeg` and `mpv` require
`libplacebo.so=360-64`. Upgrading that shared library requires a coordinated
package set and rebuilt FFmpeg filter. A later
[private API 387 build](libplacebo-upscale-private.md) does run the filter on
the N1X for 60 frames; it leaves the installed ABI and packages untouched.
No package was changed in this check.
Installed mpv's own libplacebo Vulkan renderer has already passed separate
playback tests; this result applies to FFmpeg's export filter.
