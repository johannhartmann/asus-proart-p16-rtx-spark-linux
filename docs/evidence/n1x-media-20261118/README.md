# N1X media qualification, 18 November 2026

Machine: ASUS ProArt P16 H7607BA, BIOS H7607BA.300, kernel
`7.2.8-36-rtx-spark-npu`, NVIDIA 615.78.08. The machine inventory is in
[`platform-inventory.json`](platform-inventory.json); V4L2 camera nodes,
formats and privacy controls are in [`camera-v4l2-inventory.log`](camera-v4l2-inventory.log)
with device serials redacted. Installed media packages
were FFmpeg 9.0.2-2, `libva-nvidia-driver` 0.0.18-1, mpv 0.41.0-6, and
OBS Studio 32.2.2-1. [`result.json`](result.json) records binary hashes,
return codes and stream metadata. Camera pixels and recordings were not
retained.

| Path | Result | Evidence and limit |
| --- | --- | --- |
| NVDEC via VA-API | Pass for 30-frame H.264, HEVC Main and AV1 Main 8-bit samples, plus HEVC/AV1 10-bit samples | `vaapi-*.log` selects `VA-API NVDEC driver [direct backend]` and VA-API frame surfaces; these cases do not qualify the complete codec/profile matrix. |
| NVDEC via direct CUVID | Pass for 30-frame H.264, HEVC and AV1 8-bit samples, plus HEVC/AV1 10-bit samples | The isolated FFmpeg candidate's `cuvid-*.log` selects the named `*_cuvid` decoder and completes 30 frames per case. This is separate from its failing NVENC encoder API. |
| NVIDIA Vulkan Video encode | Pass for 30-frame H.264, HEVC and AV1 8-bit samples, plus HEVC and AV1 10-bit samples | `vulkan-*.log` selects RTX Spark N1X and the codec encode extension; `*-probe.log` and `*-decode.log` verify output metadata, 10-bit pixel format where applicable, and independent software decode. This is a distinct API from NVENC. |
| Live RGB camera → Vulkan Video H.264 | Pass for a 60-frame recording in FFmpeg | `camera-vulkan-h264.log`, probe and decode logs show `/dev/video0` MJPEG 1280×720/30, N1X Vulkan Video encode, and 60 independently decoded nonconstant frames. The temporary recording was deleted. This is real camera usage of a supported Linux hardware encoder, not an NVENC API result. |
| Packaged camera command | Built; direct command run passes | [`p16-media-tools`](../../../platform/video/tools/README.md) 0.1.0-1 contains the stable P16 V4L2 camera path. `p16-record-camera-vulkan.log` records a two-second command run producing 60 H.264 1280×720/30 frames, independently checked with FFprobe. The package archive SHA256 is `05d0a675be4d2254fad424aa292095f70b0d082be00ac801026d7fbf50f96090`; this row alone does not prove the package was installed. |
| NVENC API | Blocked | The isolated [FFmpeg package](../../../platform/video/README.md) compiles all three encoders, but `nvenc-h264.log` records `OpenEncodeSessionEx failed: incompatible client key (21)` on the installed driver. No NVENC session or output was produced. |
| Desktop playback | Pass for one H.264 sample | `mpv-vaapi.log.gz` records hardware decode, libplacebo `gpu-next` output and EOF; `mpv-software-control.log` records intentional software decode. Key lines from the full mpv logs are in `mpv-summary.log`. |
| Vulkan scaling and frame mixing | Application path exercised | `mpv-effects.log.gz` records NVIDIA Vulkan/libplacebo, `ewa_lanczos`, interpolation, 320×180 source scaled to a 1190×718 and then 1400×960 Wayland window, and EOF. It does not establish AI super-resolution, generated motion frames, HDR or image-quality acceptance. |
| Desktop HDR output | Open | [`hdr-display-state.log`](hdr-display-state.log) records both connected outputs in Hyprland's `srgb` preset, default DRM Colorspace and no active HDR metadata. This session cannot qualify an SDR-to-HDR playback path or NVIDIA TrueHDR. |
| P16 internal RGB / IR cameras | Pass for bounded V4L2 capture | `p16-rgb.log` records 30 MJPEG 1280×720 frames; `p16-ir.log` records 15 GREY 360×360 frames. Per-frame luma statistics vary and the streams contain nonuniform pixels. No frames were saved. |
| RGB camera in normal applications | Pass for mpv preview and OBS recording | `mpv-rgb-camera.log.gz` shows a live 1280×720 source in a Wayland window. `obs-camera.log` shows `v4l2_input` at 1280×720/30 and a temporary six-second H.264 recording; independent FFprobe/FFmpeg read 180 frames. OBS reported 181 output frames, so the one-frame accounting difference remains to investigate. OBS logged one V4L2 select timeout when the source was added. |
| OBS advanced Vulkan recording | Blocked | `obs-vulkan-record-fail.log` records an isolated FFmpeg output profile with `h264_vulkan`; OBS reported `Failed to open video codec: Invalid argument` and produced no recording. The tested OBS path cannot yet consume Vulkan Video directly. |
| Browser/WebRTC RGB preview | Pass for a bounded Chromium `getUserMedia` run | [`browser-camera.json`](browser-camera.json) records the selected `ASUS FHD webcam`, 1280×720/30, and 30 varying preview frames. [`check-browser-camera.mjs`](../../../scripts/check-browser-camera.mjs) uses a local secure origin and auto-accepts the permission prompt, with no fake media device. This headless test does not qualify the normal graphical permission flow or PipeWire camera portal. |

The command-line corpus was run with:

```sh
python3 scripts/check-n1x-media.py \
  --output-dir docs/evidence/n1x-media-20261118 --camera \
  --camera-vulkan-record \
  --nvenc-candidate platform/video/src/ffmpeg-9.0.2/ffmpeg-n1x
```

The package was built cleanly as `ffmpeg-n1x-video 9.0.2-2`, then rebuilt
with the correct GPL-2.0-or-later license metadata as `9.0.2-3`. SHA256 of the
final package archive is `3a9643bf8343928a95978d9e25617c576569688102285abef8d14f9a5f66f39f`.
Both executables started after extraction from the archive. The latest corpus
has 17 passing cases and one failing case. No new NVRM/Xid or IOMMU fault was
present in the kernel journal during the later tests. The exit status is 1
because the NVENC runtime probe fails. That failure is
intentional and must remain visible. The generated video fixtures lived only
in a temporary directory. The OBS test used an isolated temporary profile,
muted both audio inputs, recorded to `/tmp`, probed the result and deleted it.
The browser check is repeated with:

```sh
node scripts/check-browser-camera.mjs docs/evidence/n1x-media-20261118/browser-camera.json
```

The internal RGB camera's V4L2 `privacy` control reported 0 and read-only;
the physical privacy behavior has not yet been tested. `/dev/video2` is the
internal IR device; no face-authentication claim follows from capture.

Still open: NVENC API session on a supported driver; full codec/profile and
advanced encode matrix; OBS hardware encode or another desktop recording app
using the validated Vulkan encoder; graphical browser permission and PipeWire
camera portal; device privacy and contention; audio sync, seek and longer playback;
fresh boot and physical s2idle/resume; HDR display output; proprietary NVIDIA
VSR/Frame Generation/TrueHDR Linux ARM64 artifacts; camera drivers on a
separate N1X MIPI/CSI machine. No MIPI/CSI devices are present on this P16.
