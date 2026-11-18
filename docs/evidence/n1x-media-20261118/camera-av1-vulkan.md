# Live P16 camera to Vulkan Video AV1

The [probe](../../../scripts/check-camera-av1-vulkan.py) records the internal
ASUS RGB camera's MJPEG 1280×720 stream through the distribution FFmpeg's
`av1_vulkan` encoder on the NVIDIA RTX Spark N1X. It uses
`-fps_mode passthrough` so output frame duplication cannot disguise a slow
camera. It compares FFmpeg's input and output frame counts, probes AV1 Main
1280×720 and strictly increasing packet timestamps, and decodes the complete
bitstream with both FFmpeg/libdav1d and the separate libaom `aomdec`. All
camera pixels and bitstreams are deleted after the checks.

| Camera control | Real input / encoded output | AV1 frames decoded by libdav1d / libaom | Distinct decoded frames | Packet PTS span | Startup-inclusive encode time |
| --- | ---: | ---: | ---: | ---: | ---: |
| `exposure_dynamic_framerate=1` (original setting) | 60 / 60 | 60 / 60 | 60 | 5.900 s | 8.426 s |
| Temporarily set to `0`, then restored to `1` | 60 / 60 | 60 / 60 | 60 | 1.967 s | 4.009 s |

The [original-control report](camera-av1-vulkan-kernel38/camera-av1-vulkan.json)
and [fixed-30-fps report](camera-av1-vulkan-fixed30-kernel38/camera-av1-vulkan.json)
include the boot, kernel, driver, executable hashes, bitstream hashes and
individual checks. Their adjacent logs retain the encoder, probe and decoder
output without the recording. Both runs used kernel
`7.2.8-38-rtx-spark-npu`, NVIDIA 615.78.08 and default AV1 Vulkan rate
control. The V4L2 control was `1` again after the fixed-rate probe.

The advertised 30 fps V4L2 mode did not guarantee 30 distinct input frames
per second while dynamic exposure frame rate was enabled: a separate pure
MJPEG capture also obtained 60 frames in roughly six seconds. A first AV1
trial without `-fps_mode passthrough` encoded 60 output frames from only 21
camera input frames due to FFmpeg frame duplication; it was discarded as a
camera-throughput result. With passthrough and the camera control set to `0`,
the PTS span shows about 30 real frames/s for this bounded run. The wall time
includes opening the camera and encoder, so it is not a steady-state
throughput measurement.

This qualifies one Linux V4L2 → FFmpeg → NVIDIA Vulkan Video AV1 capture
path. It does **not** prove NVENC API availability, AV1 quality, A/V sync,
sustained throughput, post-resume behavior or normal-application integration.
The [rate-control matrix](av1-vulkan-ratecontrol.md) still finds corrupt AV1
output with a 2 Mbit/s target and CQP 30 on this stack. Recording applications
must not assume those options are safe because this default-mode capture
passed.

## Packaged recorder candidate

The extracted `p16-media-tools 0.1.0-9` candidate adds `--av1` to
`p16-record-camera-vulkan`, uses passthrough timestamps for both codecs, and
offers `--fixed-fps` with restoration of the original camera control. The
[candidate test](camera-av1-packaged-candidate.json) invoked the exact binary
from the package build for two-second H.264 and AV1 recordings. Each produced
60 distinct, software-decodable 1280×720 frames with a roughly two-second PTS
span; libaom also decoded all 60 AV1 frames. The camera control returned to
`1` after each run and both temporary recordings were deleted. The package
archive SHA256 is in the report. The candidate is **not installed** at this
point, so this is application-command qualification of the extracted package,
not an installed-path result.

Repeat from the repository root with new output directories:

```sh
python3 scripts/check-camera-av1-vulkan.py \
  --output-dir docs/evidence/n1x-media-20261118/camera-av1-vulkan-recheck
python3 scripts/check-camera-av1-vulkan.py --lock-30fps \
  --output-dir docs/evidence/n1x-media-20261118/camera-av1-vulkan-fixed30-recheck
```

`--lock-30fps` reads the existing V4L2 control, temporarily sets it to `0`
and restores the original value in a `finally` block, including on an encode
or decoder failure. The report verifies the final value.
