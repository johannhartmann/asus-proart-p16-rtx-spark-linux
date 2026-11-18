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
| NVDEC via VA-API | Pass for 30-frame H.264, HEVC Main and AV1 Main 8-bit samples, HEVC/AV1 10-bit, VP9 8/10/12-bit, VP8, MPEG-2 and MJPEG | `vaapi-*.log` selects `VA-API NVDEC driver [direct backend]` and VA-API frame surfaces; these cases do not qualify the complete codec/profile matrix. |
| NVDEC via direct CUVID | Pass for 30-frame H.264, HEVC and AV1 8-bit samples, HEVC/AV1 10-bit, VP9 8/10/12-bit, VP8, MPEG-2 and MJPEG | The isolated FFmpeg candidate's `cuvid-*.log` selects the named `*_cuvid` decoder and completes 30 frames per case. This is separate from its failing NVENC encoder API. |
| HEVC RExt 12-bit decode | Pass for bounded CUVID and VA-API pixel comparison, plus installed player | [`hevc12-result.json`](hevc12-result.json) records a 30-frame x265 12-bit fixture, CUVID output with all frame hashes equal to software decode, and 30 frames on the NVIDIA VA-API direct backend. A later [VA-API `p012le` readback](hevc12-vaapi-readback-kernel38.md) matches all 30 software-decoded frames byte-for-byte with `-threads 1`; default-thread readback stalled. [`hevc12-player.log`](hevc12-player.log) shows the installed `p16-video-play` selected VA-API `p012`, rendered with `gpu-next` and reached EOF. The raw bitstream has no timestamps, so playback timing and audio sync are not qualified. |
| HEVC RExt 4:4:4 10/12-bit decode | CUVID pixels, timed VA-API/Vulkan application playback and isolated patched VA-API readback pass | [`hevc44412-result.json`](hevc44412-result.json) records 30 CUVID 12-bit frames matching software output. The installed player with `--hwdec=hevc-vulkan` reports `vulkan[p412]` and EOF in [`hevc44412-player-vulkan.log`](hevc44412-player-vulkan.log). [8-bit VA-API readback](hevc4448-vaapi-readback-kernel38.json) matches 30 software frames byte-for-byte. [High-depth VA-API readback comparison](hevc444-vaapi-readback.md) shows that distribution FFmpeg offers no valid 16-bit download and its `yuv444p` pixels are wrong; the isolated Q416-mapped package binary downloads 30 `yuv444p16le` frames byte-identical to software for both 10-bit and 12-bit fixtures. A [timed Matroska application test](hevc44412-vaapi-player-kernel38/hevc44412-vaapi-playback.json) reached EOF through CUVID and VA-API in both the installed 9.0.2-5 and extracted 9.0.2-6 FFplay Vulkan players. The extracted [9.0.2-7 package](libplacebo-api360-compat.md) repeats the 10/12-bit readback and timed playback passes. The Q416 patch enables FFmpeg CPU readback; installed package qualification remains open. The older raw 12-bit fixture had no PTS. |
| HEVC pro-format matrix | 4:4:4 8/10-bit Vulkan playback passes; 4:2:2 mpv hardware path open | [`hevc-pro-matrix.json`](hevc-pro-matrix.json) records 30-frame software/CUVID pixel-hash equality for all five cases. Mpv with explicit Vulkan Video decoding selects `nv24` for 4:4:4 8-bit and `p410` for 4:4:4 10-bit. VA-API advertises neither 4:2:2 profile; FFmpeg logs a failed VA-API setup then finishes through software. Mpv likewise plays all three 4:2:2 cases through software despite the requested Vulkan backend. Process exit 0 alone is therefore not a hardware pass. |
| H.264 pro-format matrix | High 4:2:2 8/10-bit CUVID pixels and installed FFplay Vulkan playback pass; High 4:4:4 8/10-bit rejected | The [kernel38 matrix](installed-h264-pro-kernel38/README.md) records 30-frame byte equality for High 4:2:2 at 8/10 bits, `nv16`/`p210le` renderer input and timed EOF in installed FFplay. CUVID explicitly rejects High 4:4:4 Predictive at both depths. VA-API requests exit 0 by falling back to software for all four pro formats, with no `vaapi` output frames. |
| Older FFplay SDL 4:2:2 path | Decoder passes; renderer converts to 4:2:0 | The [9.0.2-4 installed matrix](installed-ffplay/hevc-pro-matrix.json) shows CUVID pixel equality for 8/10/12-bit 4:2:2, but FFplay creates an `IYUV` texture. The [timed AAC test](installed-ffplay/hevc422-av-ffplay.json) reached EOF with audio. Its display conversion is the negative control for the new Vulkan renderer. |
| Installed FFplay Vulkan 4:2:2 path | Pass for 8/10/12-bit hardware decode and renderer input | The [9.0.2-5 installed matrix](installed-ffplay-vulkan/hevc-pro-matrix.json) shows `/usr/bin/ffplay-n1x -enable_vulkan -vcodec hevc_cuvid` decoding 8/10/12-bit 4:2:2 with pixels matching software. Libplacebo receives `nv16`, `p210le` and `p212le`, respectively, without a logged `auto_scale` or SDL `IYUV` texture. The [build and qualification record](ffplay-vulkan.md) pins the package archive and binary hashes. Final physical display precision remains unmeasured. |
| Timed Vulkan HEVC 4:2:2 plus AAC | Pass with installed FFplay | [`installed-ffplay-vulkan/timed/hevc422-av-ffplay.json`](installed-ffplay-vulkan/timed/hevc422-av-ffplay.json) and its raw log show a six-second 144-frame HEVC RExt 4:2:2/AAC clip through CUVID and libplacebo on the N1X. It reached EOF; 184 sampled A/V offsets were at most 27 ms. No 4:2:0 filter conversion was logged. |
| Kernel allocation warning during installed matrix | Open stability finding | Two NVRM `NV_ERR_NO_MEMORY` lines occurred during the 4:4:4 10-bit application playback. The [incident record](nvrm-memory-warning.md) includes the kernel lines and a targeted clean repeat. The matrix's successful exit does not erase this warning. |
| NVIDIA Vulkan Video encode | Pass for 30-frame H.264, HEVC and AV1 8-bit samples, plus HEVC and AV1 10-bit samples | `vulkan-*.log` selects RTX Spark N1X and the codec encode extension; `*-probe.log` and `*-decode.log` verify output metadata, 10-bit pixel format where applicable, and independent software decode. This is a distinct API from NVENC. |
| AV1 Vulkan Video explicit rate control | Selected bounded modes pass; bitrate and CQP 30 corrupt output | The [bounded comparison and kernel38 matrix](av1-vulkan-ratecontrol.md) use FFmpeg 9.0.2-2 and NVIDIA 615.78.08. Default, CQP 10, quality 1, tune HQ and usage record produce 24 frames accepted by both libdav1d and libaom. `-b:v 2M` and CQP 30 return encode success but produce corrupt AV1. These sampled successes do not qualify a general rate-control range or real recording. |
| Live RGB camera → Vulkan Video H.264 | Pass for a 60-frame recording in FFmpeg | `camera-vulkan-h264.log`, probe and decode logs show `/dev/video0` MJPEG 1280×720/30, N1X Vulkan Video encode, and 60 independently decoded nonconstant frames. The temporary recording was deleted. This is real camera usage of a supported Linux hardware encoder, not an NVENC API result. |
| Live RGB camera → GStreamer Vulkan H.264 | Pass for 60 frames | The installed `p16-record-camera-gstreamer` sends real P16 MJPEG camera frames through FFmpeg decode, GStreamer `rawvideoparse`/`vulkanupload` and `vulkanh264enc`. [`gstreamer-camera-vulkan.json`](gstreamer-camera-vulkan.json) and the [pipeline log](gstreamer-camera-vulkan.log) show 60 independently decoded H.264 1280×720 frames and 60 distinct downscaled frame hashes. Footage was deleted. This is Vulkan Video, not NVENC or OBS. |
| Dedicated nvJPEG hardware engine | Unavailable in current N1X runtime | [`nvjpeg-capability.json`](nvjpeg-capability.json) from the [direct CUDA API probe](../../../scripts/probe-nvjpeg-capability.c) records zero hardware JPEG decode/encode engines. Explicit hardware decoder and encoder backends return `NVJPEG_STATUS_ARCH_MISMATCH` (7). A separate [GPU-compute decode and encode](nvjpeg-gpu-batch-kernel38.md) passes pixel checks and shows nvJPEG GPU Huffman and encoder kernels; it does not establish a dedicated engine. |
| N1X Optical Flow Accelerator | Pass for API and installed video analysis | [Application record](nvof-application.md) and [`nvof-application.json`](nvof-application.json) show the packaged `p16-optical-flow` using NVIDIA's CUDA Optical Flow API 2.0 on the N1X. Identical textured frames produce mean magnitude 0.0002 pixels; an 8-pixel translated image produces mean horizontal flow 8.0000 pixels. A real 60-frame P16 camera recording was processed for 30 pairs and then deleted. This demonstrates the optical-flow engine in an installed Linux video-analysis workflow; installed export is tested separately below. |
| NVOFA midpoint video export | Installed application path passes bounded tests | [Interpolation record](nvof-interpolation.md) and [`nvof-interpolation.json`](nvof-interpolation.json) show both installed 0.1.0-4 commands using forward/backward hardware flow, source-resolution midpoint warping and Vulkan Video H.264 export. Controlled translations at 320×180 and 1280×720 match the four-pixel midpoint, a 24→48 fps AAC fixture ends audio/video within 16 ms, and a real 1280×720 camera clip exports 60→119 frames at 30→60 fps then plays in mpv with hardware decode. An [occlusion fixture](nvof-occlusion.json) improves over crossfade but has boundary error. A [20-second camera export](nvof-20s-soak.json) produced and independently decoded 1199 frames in 33 seconds. Human visual acceptance and hours-long exports remain open. |
| Packaged P16 media commands | Installed paths pass their bounded workloads | [`p16-media-tools`](../../../platform/video/tools/README.md) 0.1.0-7 is installed. The earlier [`installed-tools.json`](installed-tools.json) covers version 0.1.0-1 playback and recording; the [HDR record](hdr-output.md) covers `p16-hdr-play`, and the GStreamer recorder is covered above. The [browser record](browser-vaapi.md) covers the installed Chrome launcher, the [camera privacy record](camera-privacy.md) covers the USB authorization switch, and the [OBS bridge record](obs-vulkan-bridge.md) covers the hardware recording command. The earlier `p16-video-play-installed.log.gz` and `p16-record-camera-vulkan-installed.log` verify VA-API/Vulkan playback and live RGB recording. `pacman -Qkk` reports 19 files and none altered. Current package archive SHA256: `6cb083cebaa6e4ba6ffc3ca55bb1b4518b85572a2c5933bf1c4f2f39be597f26`. |
| Interactive A/V playback | Pass for a bounded H.264/AAC fixture | [`av-playback.json`](av-playback.json) and `av-playback-mpv.log.gz` show the installed player selecting VA-API decode, Vulkan `gpu-next` output and PipeWire audio. IPC drove forward and backward seek, pause, resume and EOF. The sampled audio/video clock difference during playback was at most 22 ms. This does not establish perceived lip sync or a long-duration stability result. |
| NVENC API | Blocked for H.264, HEVC and AV1 | The isolated [FFmpeg package](../../../platform/video/README.md) compiles all three encoders, but each `nvenc-*.log` records `OpenEncodeSessionEx failed: incompatible client key (21)` on the installed driver. The [API-version comparison](nvenc-api-version-compare.json) repeats all three probes with codec headers 12.2 and 13.1; both fail at session creation. The independent [direct C probe](nvenc-direct-session.json) creates the API function table but also gets status 21 opening a CUDA/NVENC session with either header. No NVENC output was produced. |
| NVENC OpenGL device type | Blocked at session creation | The [EGL/OpenGL probe](nvenc-opengl-session.md) creates a current NVIDIA N1X GL context, creates the NVENC API instance, then gets status 21 at `NvEncOpenEncodeSessionEx` with either 12.2 or 13.1 headers. This excludes a CUDA-only caller mistake on driver 615.78.08. An aarch64 620.70.06 driver exists and lists N1X PCI ID `2E03`, but NVENC behavior on it is not yet tested. |
| NVIDIA 620.70.06 offline audit | Source and module build pass; runtime untested | The [audit](nvenc-620-offline.md) verifies the published archive SHA256, applies all three local NVIDIA patches without fuzz and builds five version-matched modules for kernel36. The installed and running driver is still 615.78.08. This is not an NVENC result or native suspend qualification. |
| Installed NVENC check | Blocked for H.264, HEVC and AV1 | [`installed-nvenc/installed-nvenc.json`](installed-nvenc/installed-nvenc.json) and its three codec logs repeat the session probe with `/usr/bin/ffmpeg-n1x` from the installed 9.0.2-4 package. Every codec exits 187 at `OpenEncodeSessionEx` error 21. The probe exits nonzero by design when the hardware encoder is unavailable. |
| Latest installed NVENC check | Blocked for H.264, HEVC and AV1 | [`installed-nvenc-vulkan/installed-nvenc.json`](installed-nvenc-vulkan/installed-nvenc.json) repeats the same probe with package 9.0.2-5. All three codecs still fail opening the NVENC session with error 21. |
| Desktop playback | Pass for one H.264 sample | `mpv-vaapi.log.gz` records hardware decode, libplacebo `gpu-next` output and EOF; `mpv-software-control.log` records intentional software decode. Key lines from the full mpv logs are in `mpv-summary.log`. |
| Vulkan scaling and frame mixing | Application path exercised | `mpv-effects.log.gz` records NVIDIA Vulkan/libplacebo, `ewa_lanczos`, interpolation, 320×180 source scaled to a 1190×718 and then 1400×960 Wayland window, and EOF. It does not establish AI super-resolution, generated motion frames, HDR or image-quality acceptance. |
| FFmpeg/libplacebo scaling export | Extracted API 360 package candidate processes 60 GPU frames; installation and visual quality open | The [native filter finding](ffmpeg-libplacebo-filter-kernel38.md) identifies FFmpeg's rejection of Vulkan `queue_flags=4` with libplacebo API 360. A [scoped package patch](libplacebo-api360-compat.md) fixes initialization; clean 9.0.2-7 package output passes a 60-frame tagged Spline36 filter run, both 10/12-bit Q416 readbacks and timed FFplay regression. Spline36 scores below CPU bicubic on this synthetic reference. The package is not installed yet. |
| Internal OLED HDR10 playback | Pass for the signaling and application path | [HDR output evidence](hdr-output.md) records the installed `p16-hdr-play` playing 10-bit PQ/BT.2020 HEVC through mpv Vulkan decode and an HDR10 swapchain. Hyprland switched eDP-1 to `XBGR2101010/hdr`; NVIDIA DRM used BT2020_RGB Colorspace 9 and nonzero HDR metadata. SDR state restored after normal exit and a launcher SIGKILL. The prior [`hdr-display-state.log`](hdr-display-state.log) is the SDR baseline. Visual accuracy, SDR-to-HDR conversion and NVIDIA TrueHDR remain open. |
| P16 internal RGB / IR cameras | Pass for bounded V4L2 capture | `p16-rgb.log` records 30 MJPEG 1280×720 frames; `p16-ir.log` records 15 GREY 360×360 frames. Per-frame luma statistics vary and the streams contain nonuniform pixels. No frames were saved. |
| External StreamCam UVC/XHCI DMA debug | One warning; capture still succeeds | The [current-boot investigation](camera-dma-debug.md) identifies an exact 98,304-byte URB from the attached Logitech StreamCam on `NVDA8000:00` against that host's 65,536-byte DMA segment limit. The internal ASUS cameras use a different host. A source-only UVC cap compiles but has not been loaded; no XHCI limit was raised. |
| RGB camera in normal applications | Pass for mpv preview and OBS recording | `mpv-rgb-camera.log.gz` shows a live 1280×720 source in a Wayland window. `obs-camera.log` shows `v4l2_input` at 1280×720/30 and a temporary six-second H.264 recording; independent FFprobe/FFmpeg read 180 frames. OBS reported 181 output frames, so the one-frame accounting difference remains to investigate. OBS logged one V4L2 select timeout when the source was added. |
| RGB camera V4L2 contention | Pass | [`camera-contention.json`](camera-contention.json) records a 120-frame primary capture, `Device or resource busy` and zero frames for a concurrent client, then a 10-frame capture after release. No pixels were retained. |
| Internal camera privacy | Linux USB switch passes; UVC control read-only | [Privacy record](camera-privacy.md) and [`camera-privacy-control.json`](camera-privacy-control.json) show UVC `privacy=0` with a read-only flag; setting it to 1 fails while a normal brightness write succeeds. The owner reports no physical shutter. Installed [`p16-camera-privacy self-test`](camera-privacy-switch.json) removed all four internal V4L2 nodes at `authorized=0`, restored them at 1, and passed subsequent V4L2 and Chromium capture. This software switch may reset at reboot. |
| GTK camera portal → PipeWire | Pass for native app and 30 buffers | [`camera-portal.json`](camera-portal.json) records graphical permission, a portal-provided PipeWire remote, the internal ASUS RGB node, 30 MJPEG 1280×720/30 buffers with varying nonzero sizes, and EOS. The [GTK/libportal probe](../../../scripts/check-p16-camera-portal.py) sets a Video/Capture/Camera stream role; omission caused `target not found`. No pixels were retained. Sandboxed Flatpak capture and permission revocation remain untested. |
| OBS direct Vulkan encoder | Blocked in-process | `obs-vulkan-record-fail.log` records an isolated FFmpeg output profile with `h264_vulkan`; OBS reported `Failed to open video codec: Invalid argument` and produced no recording. The generic OBS FFmpeg output lacks Vulkan device and frame upload setup. |
| OBS → NUT → Vulkan Video H.264/AAC | Installed bridge passes bounded A/V recording | The [installed bridge result](obs-vulkan-bridge.md) shows OBS recording the real P16 RGB camera and generated 997 Hz tone to raw NUT, then `/usr/bin/p16-record-obs-vulkan` using `h264_vulkan` and AAC. The final file independently decoded 208 varying 1280×720 camera frames; video/audio packet ends differed by 21 ms. No footage or source audio was retained. This is separate-process Vulkan Video, not NVENC. |
| Browser/WebRTC RGB preview | Pass for a bounded Chromium `getUserMedia` run | [`browser-camera.json`](browser-camera.json) records the selected `ASUS FHD webcam`, 1280×720/30, and 30 varying preview frames. [`check-browser-camera.mjs`](../../../scripts/check-browser-camera.mjs) uses a local secure origin and auto-accepts the permission prompt, with no fake media device. This headless browser run does not qualify its normal graphical permission flow; the GTK portal capture is recorded separately above. |
| Graphical Chromium WebRTC permission and RGB preview | Pass for 30 frames | [`browser-camera-graphical.json`](browser-camera-graphical.json) records a real browser window, user-approved permission UI, internal ASUS RGB camera at 1280×720/30, and 30 varying preview frame means. The test used a fresh profile and no fake UI or fake camera; no pixels were retained. This is distinct from the GTK camera portal run. |
| Arch ARM Chromium H.264 decode | Software fallback | [`browser-decode.json`](browser-decode.json) and [`browser-decode-nvidia-flags.json`](browser-decode-nvidia-flags.json) record complete 320×180 playback but `FFmpegVideoDecoder`. The [1280×720 core and advanced runs](browser-vaapi.md) also selected software. [`check-browser-decode.mjs`](../../../scripts/check-browser-decode.mjs) exits nonzero without an explicit VA-API decoder. |
| Google Chrome H.264, VP9 and AV1 VA-API decode | Installed path passes 1280×720 cases; H.264 uses software at 320×180 | [Browser record](browser-vaapi.md) shows the installed `p16-video-chrome` selecting `VaapiVideoDecoder` and `kIsPlatformVideoDecoder=true` for 96 frames per codec with zero drops. A later [20-second AV1 run](browser-decode-p16-av1-20s-720p.json) played 480 frames with zero drops and no concurrent kernel warning. The H.264 [libva trace summary](browser-decode-p16-libva-trace.json) confirms picture submission and surface export without errors. The earlier [`320×180 result`](browser-decode-google-chrome.json) selected software. An [NVRM allocation warning](browser-av1-nvrm-warning.md) occurred during initial AV1 playback. Real sites, hours-long playback and post-resume use remain open. |

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
has 35 passing cases and three failing NVENC cases. No new NVRM/Xid or IOMMU
fault was present during that earlier corpus, but the later installed HEVC
matrix produced the allocation warning recorded above. The corpus exit status is 1
because the NVENC runtime probes fail. Those failures are
intentional and must remain visible. The generated video fixtures lived only
in a temporary directory. The OBS test used an isolated temporary profile,
muted both audio inputs, recorded to `/tmp`, probed the result and deleted it.
The browser check is repeated with:

```sh
node scripts/check-browser-camera.mjs docs/evidence/n1x-media-20261118/browser-camera.json
node scripts/check-browser-camera.mjs docs/evidence/n1x-media-20261118/browser-camera-graphical.json --graphical-permission --browser=chromium
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode.json
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-nvidia-flags.json --nvidia-vaapi
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-google-chrome.json --nvidia-vaapi --browser=google-chrome-stable
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-chrome-simple-720p.json --nvidia-vaapi --browser=google-chrome-stable --size=1280x720
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-p16-installed-720p.json --browser=p16-video-chrome --no-test-flags --size=1280x720
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-p16-vp9-720p.json --browser=p16-video-chrome --no-test-flags --size=1280x720 --codec=vp9
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-p16-av1-720p.json --browser=p16-video-chrome --no-test-flags --size=1280x720 --codec=av1
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-p16-av1-20s-720p.json --browser=p16-video-chrome --no-test-flags --size=1280x720 --codec=av1 --seconds=20
python3 scripts/check-av1-vulkan-ratecontrol.py --output docs/evidence/n1x-media-20261118/av1-vulkan-ratecontrol.json
```

Repeat the interactive installed-player A/V test with:

```sh
python3 scripts/check-n1x-av-playback.py --output-dir docs/evidence/n1x-media-20261118
```

The direct NVENC session probe uses the installed CUDA 13.4 headers and driver
libraries. Build it once per pinned `nv-codec-headers` include directory:

```sh
cc -std=c11 -Wall -Wextra -I/opt/cuda/include \
  -I/path/to/nv-codec-headers/include scripts/probe-nvenc-session.c \
  -lcuda -lnvidia-encode -o /tmp/probe-nvenc-session
/tmp/probe-nvenc-session
python3 scripts/check-p16-camera-contention.py \
  --output docs/evidence/n1x-media-20261118/camera-contention.json
```

The direct probe deliberately exits nonzero when the encoder session fails.
Its logs show API discovery and function-table creation succeeding before
status 21. The two header versions use the same source file and runtime driver.
The bounded camera privacy and NVOFA occlusion checks are:

```sh
python3 scripts/check-p16-camera-privacy.py \
  --output docs/evidence/n1x-media-20261118/camera-privacy-control.json
p16-camera-privacy self-test
python3 scripts/check-p16-nvof-occlusion.py \
  --output docs/evidence/n1x-media-20261118/nvof-occlusion.json
python3 scripts/check-p16-nvof-soak.py \
  --output docs/evidence/n1x-media-20261118/nvof-20s-soak.json --seconds 20
```

The camera self-test requests graphical Polkit authentication and restores
authorization before it exits.
Repeat the installed package encoder check with:

```sh
python3 scripts/check-installed-nvenc.py \
  --output-dir docs/evidence/n1x-media-20261118/installed-nvenc-vulkan
```

[`vainfo-nvidia.log`](vainfo-nvidia.log) records the VA-API profile inventory.
The `libva-utils 2.24.0-1` ARM64 package was extracted without installation;
its Arch Linux ARM signature verified against the local trusted keyring.
All listed entries are `VAEntrypointVLD` except `VAProfileNone` video processing;
the bridge advertises no encode entrypoint.

For the HEVC 12-bit decode test, build x265 4.3 from
`https://github.com/Multicorewareinc/x265/archive/refs/tags/4.3.tar.gz`
(SHA256 `fb157f809b74dabbef5002af99489fcaebb4d0073724beffdaaf2be15cbaf7ac`)
in an isolated directory with:

```sh
cmake -S x265-4.3/source -B build -G Ninja \
  -D HIGH_BIT_DEPTH=ON -D MAIN12=ON -D ENABLE_SHARED=OFF \
  -D ENABLE_CLI=ON -D ENABLE_HDR10_PLUS=OFF -D CMAKE_BUILD_TYPE=Release
cmake --build build -j16
```

Then run the probe from the repository root:

```sh
python3 scripts/check-hevc12-nvdec.py \
  --x265-12 /path/to/isolated/build/x265 \
  --ffmpeg-cuvid platform/video/src/ffmpeg-9.0.2/ffmpeg-n1x \
  --player /usr/bin/p16-video-play \
  --ffplay-cuvid platform/video/pkg/ffmpeg-n1x-video/usr/bin/ffplay-n1x \
  --output-dir docs/evidence/n1x-media-20261118
python3 scripts/check-hevc12-nvdec.py \
  --x265-12 /path/to/isolated/build/x265 \
  --ffmpeg-cuvid platform/video/src/ffmpeg-9.0.2/ffmpeg-n1x \
  --chroma 444 --player /usr/bin/p16-video-play \
  --vulkan-player /usr/bin/p16-video-play \
  --output-dir docs/evidence/n1x-media-20261118
```

The 12-bit test uses generated frames and deletes the raw and encoded fixture
after verification. `hevc12-*.log` retains the build's runtime behavior and
frame hashes. x265 was built only for fixture generation, not installed.
The HEVC pro-format matrix also uses the installed 8-bit x265 4.3-1 and an
isolated 10-bit build from the same pinned x265 4.3 source. Configure the
10-bit build with the 12-bit command above, replacing `-D MAIN12=ON` with
`-D MAIN12=OFF` and using a separate build directory. Then run:

```sh
python3 scripts/check-hevc-pro-matrix.py \
  --x265-8 /usr/bin/x265 \
  --x265-10 /path/to/isolated/build10/x265 \
  --x265-12 /path/to/isolated/build/x265 \
  --ffmpeg-cuvid platform/video/src/ffmpeg-9.0.2/ffmpeg-n1x \
  --player /usr/bin/p16-video-play \
  --output-dir docs/evidence/n1x-media-20261118
```

Each `hevc-{422,444}-*bit-*.log` retains the source, decoder and application
output with temporary paths redacted. The test expects mpv's software fallback
for 4:2:2 and separately verifies the isolated FFplay CUVID path.
The earlier 9.0.2-4 package was tested with the same matrix, using
`--ffmpeg-cuvid /usr/bin/ffmpeg-n1x --ffplay-cuvid /usr/bin/ffplay-n1x`
and `--output-dir docs/evidence/n1x-media-20261118/installed-ffplay`.
Repeat the current 9.0.2-5 installed 4:2:2 renderer matrix with:

```sh
python3 scripts/check-hevc-pro-matrix.py \
  --x265-8 /usr/bin/x265 \
  --x265-10 /path/to/isolated/build10/x265 \
  --x265-12 /path/to/isolated/build/x265 \
  --ffmpeg-cuvid /usr/bin/ffmpeg-n1x \
  --player /usr/bin/p16-video-play \
  --ffplay-cuvid /usr/bin/ffplay-n1x \
  --ffplay-vulkan /usr/bin/ffplay-n1x \
  --chroma-only 422 \
  --output-dir docs/evidence/n1x-media-20261118/installed-ffplay-vulkan
```

Repeat the timed 4:2:2/AAC application test with:

```sh
python3 scripts/check-hevc422-av-playback.py \
  --ffplay /usr/bin/ffplay-n1x \
  --vulkan \
  --output-dir docs/evidence/n1x-media-20261118/installed-ffplay-vulkan/timed
```

The internal RGB camera's V4L2 `privacy` control reported 0 and read-only;
the owner reports no physical shutter. The installed USB authorization switch
passed its off/on self-test and later application capture. `/dev/video2` is the
internal IR device; no face-authentication claim follows from capture.
PipeWire 1.6.10 and WirePlumber 0.5.18 expose the ASUS RGB V4L2 node as a
`Video/Source`; `org.freedesktop.portal.Camera` reports
`IsCameraPresent=true`. The registered native GTK app
`io.github.johannhartmann.P16CameraPortalProbe` received graphical camera
permission through libportal. Its portal-provided PipeWire remote exposed the
ASUS RGB node, and GStreamer received 30 JPEG buffers with EOS. The initial
`pipewiresrc` attempts reached `target not found` because they omitted
`media.type=Video, media.category=Capture, media.role=Camera` from stream
properties. The corrected path passed twice; the final result is
[`camera-portal.json`](camera-portal.json). The earlier CLI-created `no`
decision for an unregistered app ID was removed before this test. No camera
pixels were saved. A sandboxed application and post-resume capture still need
their own tests.

Later [kernel37 native evidence](../kernel37-native-20261118.md) found a
94,208/65,536-byte DMA-debug warning on the internal camera's XHCI host. A
[live UVC candidate](uvc-dma-live-kernel37.md) capped its RGB URBs and passed
RGB, IR and GStreamer/Vulkan capture without a new warning; a fresh patched
boot remains open. The [120-second NVOFA concurrent-load run](nvof-120s-concurrent-build.md)
exported every captured pair but recorded eight fewer source frames than its
exact cadence gate requires.

Still open: NVENC API session on a supported driver; full codec/profile and
advanced encode matrix, including 12-bit hardware encoding (the installed
Vulkan encoder rejects a 12-bit input in [`hevc12-vulkan-unavailable.log`](hevc12-vulkan-unavailable.log));
direct OBS in-process hardware encode and longer OBS bridge runs;
browser HEVC and deep-profile decode,
longer browser stability, explicit AV1 Vulkan rate-control modes; camera LED
behavior and privacy state across reboot; perceived A/V sync and longer playback;
fresh boot and physical s2idle/resume; measured 4:2:2 display precision and
proprietary NVIDIA
VSR/Frame Generation/TrueHDR Linux ARM64 artifacts; camera drivers on a
separate N1X MIPI/CSI machine. No MIPI/CSI devices are present on this P16.
The [resume preflight](../n1x-media-resume-20261118/README.md) did not start
sleep because neither tested RTC accepted a wake alarm.
