# P16 media commands

`p16-video-play FILE_OR_URL` starts mpv with the verified NVIDIA VA-API/NVDEC
decode bridge and Vulkan/libplacebo renderer. `ewa_lanczos` scaling and mpv
frame mixing are enabled. They are ordinary GPU video processing, not the
proprietary NVIDIA VSR or frame-generation SDK. Other mpv arguments can follow
the media path.

For HEVC 4:4:4 12-bit material on this P16, use
`p16-video-play FILE --hwdec=hevc-vulkan`. The bounded test selected Vulkan
Video decode and a `p412` renderer surface. The default VA-API path played the
same fixture but reported a `yuv444p` surface, so its 12-bit preservation is
unqualified. This does not establish HDR display output or audio sync.

`p16-record-camera-vulkan SECONDS OUTPUT.mkv` records the internal P16 RGB
camera through V4L2 and the NVIDIA Vulkan Video H.264 encoder. It records
video only and refuses to overwrite an existing output. The default camera
path is the P16 internal USB port's stable V4L2 `by-path` link; override it
with `P16_RGB_DEVICE` if device enumeration changes. The command does not
implement audio capture, camera privacy control, OBS integration or NVENC.

These commands use distribution mpv and FFmpeg. The [media evidence](../../../docs/evidence/n1x-media-20261118/README.md)
records the exact machine and driver qualification. They should be installed
only on the tested P16 model or after checking equivalent hardware paths on
another machine.
