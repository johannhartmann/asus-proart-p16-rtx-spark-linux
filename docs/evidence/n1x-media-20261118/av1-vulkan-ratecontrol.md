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

## Native kernel38 cross-decoder matrix

The [expanded IVF matrix](av1-vulkan-ratecontrol-matrix-kernel38.json), generated
by [`check-av1-vulkan-ratecontrol-matrix.py`](../../../scripts/check-av1-vulkan-ratecontrol-matrix.py),
repeats the 24-frame 1280×720 fixture on kernel38 with the same 615.78.08
driver. It checks complete frame counts with FFmpeg's `libdav1d` and the
separate `/usr/bin/aomdec` libaom decoder. All temporary bitstreams are
deleted after hashing.

| Rate-control/options | Encoder | libdav1d / libaom | Finding |
| --- | --- | --- | --- |
| Default | exit 0 | 24 / 24 frames | Bounded pass |
| `-rc_mode cqp -qp 10` | exit 0 | 24 / 24 frames | Bounded pass; no broader QP range claim |
| `-quality 1`, `-tune hq`, `-usage record` | exit 0 each | 24 / 24 frames each | Bounded bitstream pass; no quality or performance claim |
| `-rc_mode driver` without bitrate | exit 234 | No bitstream | Encoder setup fails |
| `-b:v 2M` with auto or driver mode | exit 0 | 0 frames / frame-1 failure | Corrupt AV1 output |
| `-rc_mode cqp -qp 30` or `-qp 30` with auto | exit 0 | 6 frames / frame-1 failure | Corrupt AV1 output |

The QP 10/30 contrast shows that this failure is not simply the presence of
an explicit CQP option. No application should infer a safe QP interval from
two sampled values. The default encoder path remains the only general
recording candidate here; the per-option passes need longer and real-content
qualification before becoming user controls.
