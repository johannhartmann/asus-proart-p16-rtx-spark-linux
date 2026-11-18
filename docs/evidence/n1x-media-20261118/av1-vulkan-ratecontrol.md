# AV1 Vulkan Video rate control and picture fidelity

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

The [live RGB camera AV1 capture](camera-av1-vulkan.md) extends the default
mode result to 60 distinct 1280×720 camera frames with full libdav1d and
libaom decode. Its temporary fixed-rate V4L2 setting produced a bounded
1.967-second span for 60 frames and was restored. It does not repair or
requalify the corrupt explicit bitrate and CQP 30 cases above.

## Longer real-camera and visual-quality gates

The [extended 24-frame matrix](av1-vulkan-ratecontrol-extended-kernel38.json)
passes 10, 20 and 40 Mbit/s targets and CQP 15, 20 and 25 with both decoders;
5 Mbit/s fails. Those short passes do **not** predict longer behavior. At 30
seconds, real-camera [10 Mbit/s](camera-av1-10m-30s-kernel38.json),
[20 Mbit/s](camera-av1-20m-30s-kernel38.json), and
[40 Mbit/s](camera-av1-40m-30s-kernel38.json) outputs have 903–905 monotonic
packets but only 300–605 frames decode. Encoder success and valid packet PTS
therefore cannot qualify these bitrate controls. CQP 20 and 25 each pass a
[30-second](camera-av1-cqp20-30s-kernel38.json)
[camera run](camera-av1-cqp25-30s-kernel38.json); CQP 25 also passes
[120 seconds](camera-av1-cqp25-120s-kernel38.json) with 3618/3618 frames from
both decoders and no packet gap over 50 ms. These are bitstream and timing
results, not visual-quality acceptance.

The repeatable [frame-aligned quality probe](../../../scripts/check-vulkan-encode-quality.py)
uses one 120-frame NV12 source, independently decodes every output to raw
NV12, verifies exact byte counts and compares frames by index. The
[kernel38/615 result](vulkan-encode-quality-gop-kernel38.json) is sharply
codec-specific. For every AV1 case, FFmpeg/libdav1d and the separate
`aomdec` libaom implementation produce **byte-identical 120-frame I420
pixels**. The low inter-frame PSNR is present in both decoders, not a
single-decoder artifact:

| Encoder and GOP | PSNR against exact source | Encoded bytes |
| --- | ---: | ---: |
| x264 CRF 18 reference | 46.86 dB | 2.19 MB |
| H.264 Vulkan default | 54.26 dB | 4.08 MB |
| HEVC Vulkan default | 67.52 dB | 7.16 MB |
| AV1 Vulkan default | 19.81 dB | 6.07 MB |
| AV1 Vulkan GOP 30 / 10 | 24.33 / 28.22 dB | 6.15 / 6.37 MB |
| AV1 Vulkan all-intra, GOP 1 | 63.74 dB | 9.44 MB |
| AV1 Vulkan CQP 25 / 15, GOP 30 | 24.94 / 24.29 dB | 3.72 / 4.34 MB |

AV1 frame 1 is near lossless but inter frames deteriorate within each GOP;
the default GOP's last frame is 14.74 dB. More frequent keyframes reset the
drift, while lowering QP does not reliably improve it. The precise fault
layer remains undetermined; the cross-decoder equality narrows it toward the
encoded bitstream or common interpretation. Until fixed, the P16 AV1 recorder uses GOP 1:
its [30-second real-camera run](camera-av1-intra-30s-kernel38.json) independently
decodes 905/905 frames with each decoder, restores the camera control and
occupies 305 MB versus 277 MB for the previous default-GOP recording.
Subjective camera-picture acceptance and post-resume use remain open.

The same probe's `--camera` mode captured 120 real P16 RGB MJPEG frames once,
decoded them to a shared NV12 source, restored
`exposure_dynamic_framerate=1`, and then encoded that exact source with every
mode above. The [real-camera source comparison](vulkan-encode-quality-camera-kernel38.json)
measured 31.89 dB for AV1 default GOP, 41.47 dB for GOP 10, and 53.80 dB for
all-intra GOP 1. The all-intra minimum frame was 50.15 dB; default GOP fell
to 28.87 dB. H.264 and HEVC Vulkan scored 47.08 and 58.07 dB respectively.
Libdav1d and libaom again produced byte-identical 120-frame pixels in all
six AV1 cases. The raw camera source and bitstreams were deleted; this is
objective pixel comparison, not subjective scene acceptance or proof of
post-resume behavior.
