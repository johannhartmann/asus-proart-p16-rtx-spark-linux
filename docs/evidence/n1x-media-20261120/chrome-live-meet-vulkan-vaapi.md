# Live Google Meet send-path check, 20 November 2026

## Setup

- ASUS ProArt P16 N1X/RTX Spark; kernel `7.2.8-38-rtx-spark-npu`, NVIDIA 615.78.08, Google Chrome 156.0.8078.79.
- User joined a camera-on, one-participant Meet call in the dedicated `p16-meet-chrome` profile. The existing ordinary Chrome call was left. No system change or reboot was made for this check.
- The dedicated profile's GPU process mapped `~/.local/lib/p16-vaapi-h264/nvidia_vulkan_drv_video.so`; its video-capture utility opened the internal camera at `/dev/video0`. These establish that the launcher and camera were active, not that the encoder was used.
- The meeting address, user image, audio, and browser-history data are deliberately excluded from this record.

## Active outbound video

In `chrome://webrtc-internals`, the active outbound video RTP row showed:

| Field | Observed value |
| --- | --- |
| `kind` | `video` |
| `active` | `true` |
| `codec` | `AV1` (`profile=0`, `tier=0`) |
| `encoderImplementation` | `libaom` |
| `frameHeight` | `180` |
| `scalabilityMode` | `L1T2` |
| `powerEfficientEncoder` | `false` |

This is direct Chrome WebRTC evidence that this Meet send uses a software AV1 encoder. The H.264-only VA-API bridge was loaded but cannot encode the selected AV1 stream. A six-sample `nvidia-smi` check reported 0% encoder utilization; that counter alone is not a reliable Vulkan Video usage test, so the codec and `encoderImplementation` fields are decisive here.

A five-second `/proc` CPU tick sample for the dedicated Chrome process tree totaled 157.4% of one logical CPU, including 58.8% for one renderer, 48.2% for the GPU process, and about 14% each for two utility processes. The WebRTC Internals window and Meet's picture-in-picture preview were open during this snapshot. It is diagnostic process attribution, not a controlled baseline or an attributable AV1-only CPU cost. The camera-on call had one participant and the outbound stream was only 180 pixels high; no CPU or power improvement from this bridge can be claimed from this observation.

## Consequence

The local H.264 WebRTC loopback test remains valid, but it does not predict this Meet negotiation. Meet's actual choice is AV1/libaom. [Chromium's WebRTC feature definition](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/media/webrtc/webrtc_features.cc) enables AV1 hardware encode on non-Windows platforms when an accelerator advertises it. The next implementation candidate is a Vulkan Video AV1 encode path exposed through VA-API with the profiles, rate control and temporal-layer behavior Chrome requires, followed by a local WebRTC AV1 test and a second live Meet qualification. A browser codec preference should only be used if it can be demonstrated to make Meet negotiate H.264 without breaking the call; no such mechanism was verified here.
