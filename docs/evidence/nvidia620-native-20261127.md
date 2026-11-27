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

## NVENC session failure and hardware encode control

On the same boot, the direct CUDA and EGL/OpenGL probes with Video Codec SDK
13.1 headers created their GPU contexts and the NVENC API function table.
Both returned `NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY` (21) from
`NvEncOpenEncodeSessionEx`, before codec selection. FFmpeg 9.0.2-7 repeated
the failure for each explicit encoder (`h264_nvenc`, `hevc_nvenc`,
`av1_nvenc`), exiting 187 in each case. NVML reported zero active encoder
sessions before the test.

The dynamic loader resolved `libnvidia-encode.so.1`, `libnvcuvid.so.1` and
`libcuda.so.1` to installed 620.70.06 files. All three match NVIDIA's ARM64
archive byte for byte. The loaded kernel driver and the GSP firmware also
reported 620.70.06. The encoder library SHA-256 is
`c7e0384043205899d2d95201d7262063662a5df4cf723e28f86a91266c047d94`.

A userspace ioctl observer using NVIDIA's public `NVOS54_PARAMETERS` and RM
ioctl definitions recorded the following results for both direct probes. It
logged the returned status after the real ioctl and left requests and replies
intact.

| Observation in call order | CUDA NVENC | OpenGL NVENC |
| --- | ---: | ---: |
| `NvEncodeAPICreateInstance` | 0 | 0 |
| RM control `0x20808165` | 0 | 0 |
| RM control `0x20808163` | `0x57` | `0x57` |
| `NvEncOpenEncodeSessionEx` | 21 | 21 |

The public [NVIDIA status table](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/620.70.06/src/common/sdk/nvidia/inc/nvstatuscodes.h)
names `0x57` `NV_ERR_OBJECT_NOT_FOUND`. The public command headers leave the
meaning of `0x20808163` and the identity of the missing object unresolved.
The failure reproduces outside FFmpeg and both GPU context types reach the
same RM error.

Vulkan Video allocated NVIDIA's public encoder class `NVD1B7_VIDEO_ENCODER`
(`0xd1b7`) with RM status 0 for all three control runs. The trace showed
`0x20808165` succeeding and no call to `0x20808163`. Each explicit Vulkan
encoder wrote 30 frames of 320×180 motion, `ffprobe` identified the expected
codec and counted 30 frames, and system FFmpeg independently decoded the
entire file with `-xerror`.

| Codec | NVENC API session | Vulkan Video output | Independent decode |
| --- | --- | --- | --- |
| H.264 | Error 21 | 30 frames | Pass |
| HEVC | Error 21 | 30 frames | Pass |
| AV1 | Error 21 | 30 frames | Pass |

Reproduce the NVENC session failures with the existing installed-package
probe. For a candidate that opens sessions, the [media corpus](../../scripts/check-n1x-media.py)
checks each temporary NVENC bitstream's codec, dimensions, frame count and
independent software decode. Use the distribution FFmpeg for the software
control because its AV1 decoder is `libdav1d`.

```sh
python3 scripts/check-installed-nvenc.py --output-dir /tmp/p16-nvenc-recheck
python3 scripts/check-n1x-media.py --output-dir /tmp/p16-media-check \
  --ffmpeg /usr/bin/ffmpeg --nvenc-candidate /usr/bin/ffmpeg-n1x
```

The corpus completed 32 cases successfully on this boot, including 8-bit
Vulkan H.264, HEVC and AV1, 10-bit Vulkan HEVC and AV1, and the corresponding
hardware decode tests. Its three NVENC cases failed at session open with
error 21 and the corpus exited 1.

### Offline driver comparison

The official ARM64 `620.73.04` archive matched NVIDIA's published SHA-256
`e39419152dc7b3d84de2d291adf9ab8a9003569650aa4b01ee900465a4be5e40`.
Every allocated ELF section in `libnvidia-encode.so` matches 620.70.06
byte for byte except the build-ID note. The two RM commands are still
present in the new `libnvcuvid`. The CUDA library, firmware and open kernel
sources have changes. NVIDIA's release notes name general fixes, so the
offline comparison leaves NVENC behavior on this version unverified.
[Release notes](https://www.nvidia.com/en-us/drivers/details/285530/),
[public kernel source comparison](https://github.com/NVIDIA/open-gpu-kernel-modules/compare/620.70.06...620.73.04).

The official ARM64 `610.57.04` archive matched the published SHA-256
`40279facc0429a93b0b8ec97bf59391a3d2207609894f8271b7253a14c3f8f9e`.
NVIDIA lists this P16's exact `10de:2e03`, `1043:1484` GPU and subsystem
pair. The older `libnvcuvid` also contains both RM commands. A firsthand
report of a working 610.57.04 NVENC session concerns a different ARM64
system with an RTX 5050. This makes 610.57.04 a comparison candidate whose
NVENC behavior on this P16 remains unverified.
[NVIDIA supported GPUs](https://download.nvidia.com/XFree86/Linux-aarch64/610.57.04/README/supportedchips.html),
[RTX 5050 report](https://forums.developer.nvidia.com/t/rtx-5050-on-arm64-cix-p1-nvenc-fails-with-error-21-on-driver-615-71-09-works-on-610-57-04/382838).

A private copy of the extracted 610 `kernel-open` tree accepted all three
local DRM/PM/UVM corrections with `patch --fuzz=0 -p2`. `make modules` with
`SYSSRC` and `SYSOUT` pointed to the installed kernel38 headers built all
five modules, each with 610.57.04 version, matching kernel38 `vermagic`, and
split BTF readable by `pahole` against kernel38 `vmlinux`. The build emitted
vendor warnings, primarily a GPIO const-qualification warning. An offline
ARM64 loader check resolved the 610 dependencies for NVENC, NVDEC, CUDA,
NVML, EGL and GLX from the extracted vendor libraries. The extracted driver
and build outputs are under `~/p16/video-build/driver610.57.04/`. Actual
display startup and NVENC qualification require the matched kernel modules,
firmware and userspace running on this P16.
