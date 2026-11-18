# AV1 Vulkan Video explicit rate-control failure

The [bounded 720p comparison](av1-vulkan-ratecontrol.json) runs the
distribution FFmpeg 9.0.2-2 and NVIDIA driver 615.78.08 `av1_vulkan` encoder
on 24 `testsrc2` frames at
1280×720/24 fps, then independently decodes each Matroska output with the
software AV1 decoder. The NVIDIA N1X Vulkan Video encoder returns success in
all cases. With default rate-control options, independent decoding succeeds.
With `-b:v 2M`, explicit CBR or VBR at that bitrate, or `-rc_mode cqp -qp 30`,
decoding fails with invalid AV1 data. The negative cases are intentionally
reported as `pass=false`; an encoder exit code of zero is insufficient.

This is a rate-control or driver/FFmpeg interaction on this exact stack, not
a general absence of AV1 encode capability. The existing 320×180 default
AV1 Vulkan sample also passed. The browser AV1 qualification uses an
independently validated `aomenc` fixture to avoid this encoder issue. Do not
set those explicit AV1 rate-control options in a P16 recording workflow until
the output is independently decoded on the target version.

The temporary bitstreams were deleted. No source pixels or video were
retained. The exact failing layer within FFmpeg, Vulkan Video and the NVIDIA
driver remains unknown.
