# Repaired NVIDIA 620 candidate on the P16

The 27 November 09:51 CET boot (`813b555e-92ae-43ec-92df-295340b27836`)
selected `P16 NVIDIA 620 Test` in Limine. It ran
`7.2.8-38-rtx-spark-npu` from `@nvidia620` with NVIDIA `620.70.06`.
Pacman confirmed `nvidia-utils 620.70.06-1` and the matching [ARM64 EGL
repair](nvidia620-desktop-start-20261127.md). Hyprland started and drove
the internal 3840×2400 panel at 120 Hz.

| Check | Observation |
| --- | --- |
| CUDA | Allocated device memory and copied a value to the GPU and back without error. CUDA identified RTX Spark N1X. |
| EGL/OpenGL ES | NVIDIA EGL initialized, OpenGL reported RTX Spark N1X, and the offscreen RGBA readback matched the red test pixel `255,0,0,255`. |
| Internal speaker | The two-second PipeWire playback exited zero. During duplex operation the ALSA hardware pointer advanced from 26,624 to 55,296 between two snapshots, and the HiFi1 DSP period counter advanced from 25 to 53. The speaker stall observed on the previous Kernel38/615 boot did not reproduce in this digital test. |
| Internal microphone | Capture returned 384,000 bytes of S16_LE stereo at 48 kHz, of which 314,803 were nonzero. The bounded `pw-record --sample-count` invocation returned 1 at the limit, with no stderr. The ALSA capture pointer advanced and the captured bytes were discarded. |
| Internal RGB and IR cameras | Read and decoded 60 RGB frames at 1280×720/30 and 30 IR frames at 360×360/15. Both FFmpeg commands exited zero. |
| Installed camera recorder | `p16-record-camera-vulkan` recorded 60 H.264 frames at 1280×720. Independent FFmpeg decode completed without errors. The temporary recording was deleted. |
| NVENC | The same `ffmpeg-n1x-video 9.0.2-7` binary again returned error 21 from `OpenEncodeSessionEx` for H.264, HEVC and AV1. The direct EGL/OpenGL NVENC probes also returned 21 with both the 12.2 and 13.1 headers, despite success creating the NVENC API instance. |
| External monitor via hub | The external DRM connectors showed disconnected and no EDID. The USB-C partner was present on `port1`, but there was no attached hub, USB4 link or external display in Hyprland. The failure persisted across the 615 fallback and the repaired 620 boot. |

All three DSPs reported firmware readiness and exposed their ASoC
ready state. There was one boot-time warning in `nvidia_drm` at
`nvidia-drm-crtc.h:371`. The matching 620 source warns when the driver's
flip-event handler finds no pending flip object. No additional warning,
Xid, IOMMU fault or DMA-API error was observed during the bounded
tests. This boot establishes desktop and basic GPU operation. Audible
speaker fidelity, the external StreamCam and physical suspend/resume
remain pending. Physical suspend was deferred because of the new boot
warning.
