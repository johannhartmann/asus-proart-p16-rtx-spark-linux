# Real P16 camera H.264 Vulkan timestamp order

The repeatable [`check-camera-h264-timing.py`](../../../scripts/check-camera-h264-timing.py)
uses the internal 1280×720 MJPEG camera, temporarily disables its dynamic
exposure frame-rate reduction, and passes true input frames to `h264_vulkan`
with FFmpeg's passthrough output mode. It counts V4L2 input frames, encoded
packets, independent software-decoded frames and distinct decoded frame
hashes. All temporary camera pixels and bitstreams are deleted; the camera
control is restored to its initial value.

H.264's B-frames make packet PTS appear out of order in decode order. The
[three-second control](camera-h264-packet-order-smoke3-kernel38.json) has 59
B-frames and 30 non-increasing packet PTS steps, while packet DTS and decoded
frame PTS are strictly increasing. Non-increasing **packet PTS alone** is
therefore not a failure gate. The checker tests packet DTS and presentation
timestamps after decoding separately.

| 30-second run | Input / encoded / decoded | B-frames | Packet PTS reorders | Non-increasing packet DTS / decoded PTS | Decoded gaps over 50 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Default 1/30 encoder time base](camera-h264-packet-order-30s-kernel38.json) | 905 / 904 / 904 | 599 | 303 | 8 / 8 | 4 |
| [Microsecond encoder time base](camera-h264-microsecond-packet-order-30s-kernel38.json) | 906 / 905 / 905 | 599 | 301 | 0 / 0 | 0 |
| [Extracted 0.1.0-12 recorder](camera-h264-packaged-microsecond-30s-kernel38.json) | 906 / 905 / 905 | 599 | 301 | 0 / 0 | 0 |

The microsecond run has decoded PTS gaps of 32–36 ms; all 905 decoded frames
have distinct hashes. Each direct run restores
`exposure_dynamic_framerate=1` from its temporary value 0. The exact
extracted-package command invokes `--fixed-fps`; its wrapper report checks
the control before and after but does not independently sample it while that
command runs. Each 30-second run reads one frame beyond the `-t 30` output
boundary, so strict retention of every read input remains open.

`p16-media-tools 0.1.0-12` applies `-enc_time_base 1/1000000` to both H.264
and AV1. Its clean package build passes all source hashes. The package
archive SHA256 is
`bce034bbe3e4f17f3246679fb737142eccadc0eec205aff64abd3fda99a87492`.
An [AV1 short regression from the exact package](camera-av1-package12-short-kernel38.json)
encoded 61 frames with increasing packet PTS and full libdav1d/libaom decode;
the previous package's [30-second AV1 gate](camera-av1-packaged-intra-30s-kernel38.json)
remains the longer application-command check. The 0.1.0-12 package is not
installed yet; installed-path and post-resume gates remain open.
