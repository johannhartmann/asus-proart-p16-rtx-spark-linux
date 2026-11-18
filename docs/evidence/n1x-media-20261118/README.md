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
| HEVC RExt 12-bit decode | Pass for bounded CUVID pixel comparison, VA-API decode and installed player | [`hevc12-result.json`](hevc12-result.json) records a 30-frame x265 12-bit fixture, CUVID output with all frame hashes equal to software decode, and 30 frames on the NVIDIA VA-API direct backend. [`hevc12-player.log`](hevc12-player.log) shows the installed `p16-video-play` selected VA-API `p012`, rendered with `gpu-next` and reached EOF. The raw bitstream has no timestamps, so playback timing and audio sync are not qualified. |
| HEVC RExt 4:4:4 12-bit decode | Pass for CUVID pixel comparison and installed Vulkan Video playback | [`hevc44412-result.json`](hevc44412-result.json) records 30 frames with CUVID pixels matching software decode and 30 VA-API hardware frames. The installed player with `--hwdec=hevc-vulkan` reports `vulkan[p412]` and EOF in [`hevc44412-player-vulkan.log`](hevc44412-player-vulkan.log). Its default VA-API path reports `vaapi[yuv444p]`; preservation of 12-bit precision there is not established. The raw fixture has no PTS. |
| HEVC pro-format matrix | 4:4:4 8/10-bit Vulkan playback passes; 4:2:2 mpv hardware path open | [`hevc-pro-matrix.json`](hevc-pro-matrix.json) records 30-frame software/CUVID pixel-hash equality for all five cases. Mpv with explicit Vulkan Video decoding selects `nv24` for 4:4:4 8-bit and `p410` for 4:4:4 10-bit. VA-API advertises neither 4:2:2 profile; FFmpeg logs a failed VA-API setup then finishes through software. Mpv likewise plays all three 4:2:2 cases through software despite the requested Vulkan backend. Process exit 0 alone is therefore not a hardware pass. |
| Older FFplay SDL 4:2:2 path | Decoder passes; renderer converts to 4:2:0 | The [9.0.2-4 installed matrix](installed-ffplay/hevc-pro-matrix.json) shows CUVID pixel equality for 8/10/12-bit 4:2:2, but FFplay creates an `IYUV` texture. The [timed AAC test](installed-ffplay/hevc422-av-ffplay.json) reached EOF with audio. Its display conversion is the negative control for the new Vulkan renderer. |
| Installed FFplay Vulkan 4:2:2 path | Pass for 8/10/12-bit hardware decode and renderer input | The [9.0.2-5 installed matrix](installed-ffplay-vulkan/hevc-pro-matrix.json) shows `/usr/bin/ffplay-n1x -enable_vulkan -vcodec hevc_cuvid` decoding 8/10/12-bit 4:2:2 with pixels matching software. Libplacebo receives `nv16`, `p210le` and `p212le`, respectively, without a logged `auto_scale` or SDL `IYUV` texture. The [build and qualification record](ffplay-vulkan.md) pins the package archive and binary hashes. Final physical display precision remains unmeasured. |
| Timed Vulkan HEVC 4:2:2 plus AAC | Pass with installed FFplay | [`installed-ffplay-vulkan/timed/hevc422-av-ffplay.json`](installed-ffplay-vulkan/timed/hevc422-av-ffplay.json) and its raw log show a six-second 144-frame HEVC RExt 4:2:2/AAC clip through CUVID and libplacebo on the N1X. It reached EOF; 184 sampled A/V offsets were at most 27 ms. No 4:2:0 filter conversion was logged. |
| Kernel allocation warning during installed matrix | Open stability finding | Two NVRM `NV_ERR_NO_MEMORY` lines occurred during the 4:4:4 10-bit application playback. The [incident record](nvrm-memory-warning.md) includes the kernel lines and a targeted clean repeat. The matrix's successful exit does not erase this warning. |
| NVIDIA Vulkan Video encode | Pass for 30-frame H.264, HEVC and AV1 8-bit samples, plus HEVC and AV1 10-bit samples | `vulkan-*.log` selects RTX Spark N1X and the codec encode extension; `*-probe.log` and `*-decode.log` verify output metadata, 10-bit pixel format where applicable, and independent software decode. This is a distinct API from NVENC. |
| Live RGB camera → Vulkan Video H.264 | Pass for a 60-frame recording in FFmpeg | `camera-vulkan-h264.log`, probe and decode logs show `/dev/video0` MJPEG 1280×720/30, N1X Vulkan Video encode, and 60 independently decoded nonconstant frames. The temporary recording was deleted. This is real camera usage of a supported Linux hardware encoder, not an NVENC API result. |
| Packaged P16 media commands | Installed; three commands pass their bounded paths | [`p16-media-tools`](../../../platform/video/tools/README.md) 0.1.0-2 is installed; the earlier [`installed-tools.json`](installed-tools.json) covers version 0.1.0-1 playback and recording. The new `p16-hdr-play` hash, normal playback and watchdog recovery are in [the HDR output record](hdr-output.md). The earlier `p16-video-play-installed.log.gz` and `p16-record-camera-vulkan-installed.log` still verify VA-API/Vulkan playback and two-second live RGB recording. The current package archive SHA256 is `517134eec1a88510748e0fed72c1c3c94f757ec166424256dc1dc98a6b3e18ed`. |
| Interactive A/V playback | Pass for a bounded H.264/AAC fixture | [`av-playback.json`](av-playback.json) and `av-playback-mpv.log.gz` show the installed player selecting VA-API decode, Vulkan `gpu-next` output and PipeWire audio. IPC drove forward and backward seek, pause, resume and EOF. The sampled audio/video clock difference during playback was at most 22 ms. This does not establish perceived lip sync or a long-duration stability result. |
| NVENC API | Blocked for H.264, HEVC and AV1 | The isolated [FFmpeg package](../../../platform/video/README.md) compiles all three encoders, but each `nvenc-*.log` records `OpenEncodeSessionEx failed: incompatible client key (21)` on the installed driver. The [API-version comparison](nvenc-api-version-compare.json) repeats all three probes with codec headers 12.2 and 13.1; both fail at session creation. The independent [direct C probe](nvenc-direct-session.json) creates the API function table but also gets status 21 opening a CUDA/NVENC session with either header. No NVENC output was produced. |
| Installed NVENC check | Blocked for H.264, HEVC and AV1 | [`installed-nvenc/installed-nvenc.json`](installed-nvenc/installed-nvenc.json) and its three codec logs repeat the session probe with `/usr/bin/ffmpeg-n1x` from the installed 9.0.2-4 package. Every codec exits 187 at `OpenEncodeSessionEx` error 21. The probe exits nonzero by design when the hardware encoder is unavailable. |
| Latest installed NVENC check | Blocked for H.264, HEVC and AV1 | [`installed-nvenc-vulkan/installed-nvenc.json`](installed-nvenc-vulkan/installed-nvenc.json) repeats the same probe with package 9.0.2-5. All three codecs still fail opening the NVENC session with error 21. |
| Desktop playback | Pass for one H.264 sample | `mpv-vaapi.log.gz` records hardware decode, libplacebo `gpu-next` output and EOF; `mpv-software-control.log` records intentional software decode. Key lines from the full mpv logs are in `mpv-summary.log`. |
| Vulkan scaling and frame mixing | Application path exercised | `mpv-effects.log.gz` records NVIDIA Vulkan/libplacebo, `ewa_lanczos`, interpolation, 320×180 source scaled to a 1190×718 and then 1400×960 Wayland window, and EOF. It does not establish AI super-resolution, generated motion frames, HDR or image-quality acceptance. |
| Internal OLED HDR10 playback | Pass for the signaling and application path | [HDR output evidence](hdr-output.md) records the installed `p16-hdr-play` playing 10-bit PQ/BT.2020 HEVC through mpv Vulkan decode and an HDR10 swapchain. Hyprland switched eDP-1 to `XBGR2101010/hdr`; NVIDIA DRM used BT2020_RGB Colorspace 9 and nonzero HDR metadata. SDR state restored after normal exit and a launcher SIGKILL. The prior [`hdr-display-state.log`](hdr-display-state.log) is the SDR baseline. Visual accuracy, SDR-to-HDR conversion and NVIDIA TrueHDR remain open. |
| P16 internal RGB / IR cameras | Pass for bounded V4L2 capture | `p16-rgb.log` records 30 MJPEG 1280×720 frames; `p16-ir.log` records 15 GREY 360×360 frames. Per-frame luma statistics vary and the streams contain nonuniform pixels. No frames were saved. |
| RGB camera in normal applications | Pass for mpv preview and OBS recording | `mpv-rgb-camera.log.gz` shows a live 1280×720 source in a Wayland window. `obs-camera.log` shows `v4l2_input` at 1280×720/30 and a temporary six-second H.264 recording; independent FFprobe/FFmpeg read 180 frames. OBS reported 181 output frames, so the one-frame accounting difference remains to investigate. OBS logged one V4L2 select timeout when the source was added. |
| RGB camera V4L2 contention | Pass | [`camera-contention.json`](camera-contention.json) records a 120-frame primary capture, `Device or resource busy` and zero frames for a concurrent client, then a 10-frame capture after release. No pixels were retained. |
| OBS advanced Vulkan recording | Blocked | `obs-vulkan-record-fail.log` records an isolated FFmpeg output profile with `h264_vulkan`; OBS reported `Failed to open video codec: Invalid argument` and produced no recording. The tested OBS path cannot yet consume Vulkan Video directly. |
| Browser/WebRTC RGB preview | Pass for a bounded Chromium `getUserMedia` run | [`browser-camera.json`](browser-camera.json) records the selected `ASUS FHD webcam`, 1280×720/30, and 30 varying preview frames. [`check-browser-camera.mjs`](../../../scripts/check-browser-camera.mjs) uses a local secure origin and auto-accepts the permission prompt, with no fake media device. This headless test does not qualify the normal graphical permission flow or PipeWire camera portal. |
| Chromium H.264 decode | Software fallback | [`browser-decode.json`](browser-decode.json) and [`browser-decode-nvidia-flags.json`](browser-decode-nvidia-flags.json) record complete 96-frame playback but CDP Media reports `FFmpegVideoDecoder` and `kIsPlatformVideoDecoder=false`. The second run uses the NVIDIA VA-API bridge's documented Chrome flags. [`check-browser-decode.mjs`](../../../scripts/check-browser-decode.mjs) exits nonzero without an explicit VA-API decoder. Browser hardware decoding remains open. |
| Google Chrome H.264 decode | Software fallback | [`browser-decode-google-chrome.json`](browser-decode-google-chrome.json) records 96 complete frames on Google Chrome 156 ARM64 with the same NVIDIA flags and CDP Media again reports `FFmpegVideoDecoder` with `kIsPlatformVideoDecoder=false`. This independently leaves Chrome hardware playback unqualified. |

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
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode.json
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-nvidia-flags.json --nvidia-vaapi
node scripts/check-browser-decode.mjs docs/evidence/n1x-media-20261118/browser-decode-google-chrome.json --nvidia-vaapi --browser=google-chrome-stable
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
the physical privacy behavior has not yet been tested. `/dev/video2` is the
internal IR device; no face-authentication claim follows from capture.
PipeWire 1.6.10 and WirePlumber 0.5.18 expose the ASUS RGB V4L2 node as a
`Video/Source` and `org.freedesktop.portal.Camera` reports
`IsCameraPresent=true`. This confirms discovery, not a portal capture; an
initial GStreamer `pipewiresrc` target attempt returned `target not found`.
The [GTK/libportal probe](../../../scripts/check-p16-camera-portal.py) prepares
a 30-buffer stream test. A CLI permission request was left unanswered and
stored a `no` decision for the unsandboxed app ID; that test-created decision
was removed from the permission store. No graphical approval or portal stream
has completed. The graphical permission and portal stream gates remain open.

Still open: NVENC API session on a supported driver; full codec/profile and
advanced encode matrix, including 12-bit hardware encoding (the installed
Vulkan encoder rejects a 12-bit input in [`hevc12-vulkan-unavailable.log`](hevc12-vulkan-unavailable.log));
OBS hardware encode or another desktop recording app
using the validated Vulkan encoder; browser hardware decode, graphical browser
permission and PipeWire
camera portal; physical device privacy; perceived A/V sync and longer playback;
fresh boot and physical s2idle/resume; measured 4:2:2 display precision and
HDR display output; proprietary NVIDIA
VSR/Frame Generation/TrueHDR Linux ARM64 artifacts; camera drivers on a
separate N1X MIPI/CSI machine. No MIPI/CSI devices are present on this P16.
The [resume preflight](../n1x-media-resume-20261118/README.md) did not start
sleep because neither tested RTC accepted a wake alarm.
