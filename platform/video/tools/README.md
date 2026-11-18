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

`p16-record-obs-vulkan OUTPUT.mkv` lets OBS record through the NVIDIA Vulkan
Video H.264 encoder. In OBS Output settings, select Advanced → Recording →
Custom Output (FFmpeg), output to URL, container `nut`, video encoder
`rawvideo`, audio encoder `pcm_s16le`, and audio track 1. Use
`${XDG_RUNTIME_DIR}/p16-obs-vulkan/feed.nut` as the URL. Start the bridge
command first, then Start Recording in OBS; Stop Recording closes the pipe and
finalizes the Matroska file. The helper creates the private FIFO, refuses to
overwrite an output, accepts `--bitrate 2500k` or another positive k/M value,
and removes the FIFO when it exits. Audio is optional when OBS has no active
audio track. OBS sends uncompressed NV12 frames and PCM audio; FFmpeg uploads
the video to Vulkan, encodes H.264 with `h264_vulkan`, and encodes AAC audio.
This is a standard local FFmpeg output from OBS, with a CPU copy between the
applications. It does not use the NVENC API. The [bounded camera and tone
recording](../../../docs/evidence/n1x-media-20261118/obs-vulkan-bridge.md)
independently decoded 208 changing camera frames and a 997 Hz audio tone.

`p16-video-chrome [URL or Chrome options]` starts Google Chrome with the
NVIDIA VA-API direct backend and the flags that selected `VaapiVideoDecoder`
on this P16. It uses a dedicated profile in
`${XDG_DATA_HOME:-$HOME/.local/share}/p16-video-chrome` so an already running
Chrome instance cannot silently discard the GPU flags. Set
`P16_CHROME_PROFILE` to choose another profile, or pass `--user-data-dir`.
Google Chrome is optional for the other media commands. Bounded 1280×720
H.264, VP9 and AV1 tests each played 96 frames with `VaapiVideoDecoder` and
`kIsPlatformVideoDecoder=true`. A 20-second AV1 repeat played 480 frames with
zero drops. A 320×180 H.264 fixture and Arch ARM Chromium 156 fell back to
software. An NVRM allocation warning occurred during the first short AV1
run; subsequent short and 20-second runs had no concurrent warning. Real
sites, other profiles and resolutions, hours-long playback and resume still
need qualification. The [browser record](../../../docs/evidence/n1x-media-20261118/browser-vaapi.md)
contains the exact observations.

`p16-camera-privacy status|off|on` controls Linux USB authorization for the
internal ASUS RGB/IR camera only. The privileged helper verifies the P16 ACPI
parent `NVDA8001:00` and USB ID `636e:0bdb` before changing the standard
`authorized` attribute. `off` removes the camera's V4L2 nodes; `on` restores
them. Both changes use Omarchy's graphical Polkit authentication. USB
authorization may reset after a reboot or device re-enumeration; check
`status` after either event.
`p16-camera-privacy self-test` briefly disables and restores the device in a
`finally` block to verify both transitions. Existing camera applications may
need to reopen their stream after a transition. This is a software privacy
control; the P16 has no physical camera shutter according to the owner, and
its UVC `privacy` control is read-only. The [privacy result](../../../docs/evidence/n1x-media-20261118/camera-privacy-control.json)
records that UVC limit.

These commands use distribution mpv and FFmpeg. The [media evidence](../../../docs/evidence/n1x-media-20261118/README.md)
records the exact machine and driver qualification. They should be installed
only on the tested P16 model or after checking equivalent hardware paths on
another machine.
