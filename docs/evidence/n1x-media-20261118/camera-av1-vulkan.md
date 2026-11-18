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

## Thirty-second camera timing and package correction

The first [30-second recording from the extracted 0.1.0-9
command](camera-av1-packaged-30s-kernel38.json) exposed a longer-run timing
failure: 904 AV1 packets had eight non-increasing packet PTS values and four
gaps above 50 ms. Libaom decoded all 904 packets; FFmpeg's default FrameMD5
output emitted 901 frames. That output count alone does not establish a
bitstream decode error, because FFmpeg can resynchronize frames with repeated
timestamps. The original camera control value `1` was restored.

FFmpeg rejects the documented `-enc_time_base -1` shorthand on this build at
output setup, as the [negative probe](camera-av1-source-timebase-30s-kernel38.json)
records. Explicit `-enc_time_base 1/1000000`, matching V4L2's microsecond
input time base, produces [905 strictly increasing AV1 packet timestamps over
29.989 seconds](camera-av1-source-timebase-30s-boundary-kernel38.json).
Both libdav1d with passthrough output and libaom decoded all 905 packets.
FFmpeg read 906 camera frames and encoded 905 because `-t 30` ended at the
next input boundary; the report deliberately leaves its strict all-input
gate false. No packet gap exceeded 50 ms, and the V4L2 control was restored.

`p16-media-tools 0.1.0-10` applies the explicit microsecond encoder time
base only to its AV1 mode. The [extracted-package 30-second
test](camera-av1-packaged-30s-timebase-verified-kernel38.json), run by
[`check-camera-av1-timing.py`](../../../scripts/check-camera-av1-timing.py),
records 906 actual camera input frames, 905 encoded packets, 905 distinct
libdav1d frames and 905 libaom frames. All packet PTS values increase,
the largest gap is 36 ms and the camera control returns to `1`. The single
input frame beyond the timed output remains explicitly unqualified as
strict input retention. A two-second H.264 regression from the same package
candidate independently decoded 60 frames and restored the control. The
package archive SHA256 is `71ca01e4c88284f0de7baa19787a0526a656d8f9eb71b79a7abfa8f880a29431`.
This is an extracted package, **not yet installed**; sustained quality,
A/V sync, post-resume use and strict all-input retention remain open.

## All-intra quality correction

Complete decode does not prove picture fidelity. The
[frame-aligned quality comparison](av1-vulkan-ratecontrol.md#longer-real-camera-and-visual-quality-gates)
finds severe AV1 inter-frame drift on kernel38/driver 615.78.08; H.264 and
HEVC Vulkan outputs from the same source do not show it. AV1 GOP 1 yields
63.74 dB PSNR over 120 synthetic frames versus 19.81 dB at the default GOP.

The [direct 30-second all-intra camera run](camera-av1-intra-30s-kernel38.json)
encoded 905 packets from 906 read frames, with strictly increasing timestamps
over 29.988 seconds and no gap above 50 ms. Libdav1d and libaom each decoded
all 905 frames; the camera control returned to its original value. The one
extra input frame at the `-t 30` boundary remains outside strict retention.
The output occupied 305 MB, about 10% above the 277 MB default-GOP run for
this camera scene.

`p16-media-tools 0.1.0-11` adds `-g 1` only for its AV1 mode while retaining
the microsecond encoder time base. The [extracted-package 30-second
test](camera-av1-packaged-intra-30s-kernel38.json) passes the same camera and
two-decoder gate: 905 monotonic packets, 905 distinct libdav1d frames and
905 libaom frames. The camera control reads `1` before and after the command;
the report does not independently sample it while the recorder runs. The
package archive SHA256 is
`77f002fc08aa8d284d3262639dbf29918ec796f56677f2dd41a7aa95c9bf340f`.
The package is not yet installed. This is a version-specific quality workaround, with
subjective camera-picture acceptance, A/V sync and post-resume use open.

Repeat the timing gate with a new report path:

```sh
python3 scripts/check-camera-av1-timing.py --seconds 30 \
  --recorder /usr/bin/p16-record-camera-vulkan --output NEW_JSON_PATH
```

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
