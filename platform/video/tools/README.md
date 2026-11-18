# P16 media commands

`p16-video-play FILE_OR_URL` starts mpv with the verified NVIDIA VA-API/NVDEC
decode bridge and Vulkan/libplacebo renderer. `ewa_lanczos` scaling and mpv
frame mixing are enabled. They are ordinary GPU video processing, not the
proprietary NVIDIA VSR or frame-generation SDK. Other mpv arguments can follow
the media path.

For HEVC 4:4:4 material on this P16, use
`p16-video-play FILE --hwdec=hevc-vulkan`. Bounded 8, 10 and 12-bit tests
selected Vulkan Video decode with `nv24`, `p410` and `p412` renderer surfaces.
The default VA-API path played the 12-bit fixture but reported a `yuv444p`
surface, so its 12-bit preservation is unqualified. HEVC 4:2:2 playback
falls back to software in mpv; the installed `ffplay-n1x -enable_vulkan`
uses CUVID plus libplacebo/Vulkan without observed chroma downsampling.

`p16-hdr-play HDR10_HEVC_FILE [mpv options...]` plays local HEVC files with
PQ transfer and BT.2020 primaries on the internal P16 OLED. It temporarily
sets the display to 10-bit HDR, uses mpv's Vulkan decoder and HDR colorspace
hint, and restores the Omarchy monitor configuration when playback ends.
A watchdog also restores SDR if the launcher is killed. Only one instance
can run at a time. The output path was verified with a real HDR10 stream,
including nonzero DRM HDR metadata; visual luminance and color accuracy
remain unmeasured. The external Samsung U28E590 has no HDR EDID support.
Use `p16-video-play` for ordinary SDR playback.

`p16-record-camera-vulkan SECONDS OUTPUT.mkv` records the internal P16 RGB
camera through V4L2 and the NVIDIA Vulkan Video H.264 encoder. It records
video only and refuses to overwrite an existing output. The default camera
path is the P16 internal USB port's stable V4L2 `by-path` link; override it
with `P16_RGB_DEVICE` if device enumeration changes. The command does not
implement audio capture, camera privacy control, OBS integration or NVENC.

`p16-record-camera-gstreamer SECONDS OUTPUT.h264` records the same live camera
through GStreamer's `vulkanh264enc`. FFmpeg reads and converts the camera's
MJPEG input; `rawvideoparse` and `vulkanupload` hand NV12 frames to the
NVIDIA Vulkan Video encoder. The output is an elementary H.264 video stream
without audio or container timestamps. The command refuses to overwrite an
existing file and removes partial output on failure. A 60-frame camera run
was independently decoded and checked for changing frames. This is another
standard Linux Vulkan Video API path, not NVENC or OBS integration.

These commands use distribution mpv and FFmpeg. The [media evidence](../../../docs/evidence/n1x-media-20261118/README.md)
records the exact machine and driver qualification. They should be installed
only on the tested P16 model or after checking equivalent hardware paths on
another machine.
