# Chrome solo Meet: video engine and CPU audit, 20 November 2026

The active workload was a Google Meet session with only the P16 user present,
using audio and the internal RGB camera. No meeting URL, participant data,
camera pixels or audio were recorded. The system ran kernel
`7.2.8-38-rtx-spark-npu`, NVIDIA 615.78.08, Google Chrome 156.0.8078.79,
`libva-nvidia-driver 0.0.18-1` and `p16-media-tools 0.1.0-12`.

The ordinary Chrome process was launched through
`/usr/bin/google-chrome-stable` with Omarchy's Wayland flags. It had neither
the VA-API feature flags nor `LIBVA_DRIVER_NAME=nvidia` in its process
environment. Its GPU process had `/dev/dri/renderD128`, `/dev/nvidia0` and
NVIDIA EGL libraries open, so GPU rendering was active. The NVIDIA VA-API
driver library was not mapped in that process. This is a process observation,
not a `chrome://media-internals` decoder trace.

The internal RGB V4L2 node was in `1280×720`, 30 fps MJPEG mode during Meet.
In one six-second `/proc` CPU sample, the active Chrome renderer consumed
51.5% of one CPU, the `video_capture` utility 9.1%, and the Chrome GPU
process 96.8%. Six concurrent NVML samples showed 19–22% GPU use, 0%
video-encoder use and 0–1% video-decoder use. A later four-second sample
showed 58.2%, 8.0% and 7.5% of one CPU for those three processes, with 4%
GPU use in an adjacent NVML reading. The GPU-process CPU load therefore
varied sharply; its peak should not be presented as sustained. A brief
`perf` sample showed work in Chrome and NVIDIA EGL/GL libraries, without
symbols sufficient to attribute it to a particular Meet effect.

| Path | Current availability | Consequence for this solo Meet session |
| --- | --- | --- |
| GPU rendering/compositing | Active: NVIDIA render node and EGL libraries in Chrome, nonzero GPU use | Already used; CPU work remains in the renderer and GPU process. |
| Received-video hardware decode | [The installed P16 launcher](../n1x-media-20261118/browser-vaapi.md) selected `VaapiVideoDecoder` for bounded H.264, VP9 and AV1 720p playback in a separate profile. Ordinary Chrome lacks those flags. | No remote participant was present, so enabling playback decode cannot explain or cure this measured Meet load. No decoder claim is made for this live Chrome process. |
| Camera MJPEG decode | The camera supplies 720p/30 MJPEG; Chrome's capture utility used CPU. The [installed VA-API driver inventory](../n1x-media-20261118/vainfo-nvidia.log) advertises `VAProfileJPEGBaseline: VAEntrypointVLD`, and separate FFmpeg tests exercised hardware MJPEG decode. | This proves a local JPEG hardware path exists, but does not prove Chrome's V4L2 capture service uses it. No direct camera-decoder trace was available. |
| Meet/WebRTC hardware encode | The installed VA-API bridge exposes decode (`VAEntrypointVLD`) and video processing, with no encode entrypoint in the [local inventory](../n1x-media-20261118/vainfo-nvidia.log). [Installed NVENC probes](../n1x-media-20261118/installed-nvenc-package7-kernel38/installed-nvenc.json) fail H.264, HEVC and AV1 session opening with error 21 on driver 615. Vulkan Video encoding works through separate FFmpeg/GStreamer paths, not the running Chrome WebRTC process. | No qualified GPU video encoder is available to this Chrome/Meet session on the current stack. The 0% NVML encoder readings agree but do not identify the negotiated Meet codec. |

No Chrome flags, audio route, power profile, kernel, driver or browser process
were changed during the call. In particular, enabling the experimental
NVIDIA VA-API playback path globally during a solo call would not target the
measured outgoing-video work. The exact Meet send codec, send resolution,
background effects and camera-off CPU delta were not observed because the
browser UI was unavailable to the agent. A follow-up should first compare
camera on/off in the same call, then change one Meet quality/effect setting
only if that comparison identifies the camera as the main cost. The
isolated `p16-video-chrome` launcher remains the qualified playback decoder
path; its short synthetic results do not qualify a live Meet session.
