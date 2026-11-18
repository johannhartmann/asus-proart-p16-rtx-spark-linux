# Missing N1X media support: implementation and use plan

This is the qualification path for video codecs, GPU video effects, and camera
capture on Linux/Omarchy. The goal is **a working consumer application using the
intended hardware path**, not merely a bound driver, an advertised capability,
or a successful synthetic API call. Each result belongs to an exact machine,
firmware, kernel, NVIDIA driver, userspace build, and application version.

## Baseline and scope (18 November 2026)

The reference machine is the ASUS ProArt P16 H7607BA, 20-core RTX Spark N1X.
The initial media baseline used `7.2.8-36-rtx-spark-npu` and NVIDIA
`615.78.08`; native kernel37 and kernel38 results are recorded below. NVIDIA's [N1X codec
matrix](https://developer.nvidia.com/video-encode-decode-support-matrix) lists
one ninth-generation NVENC, one sixth-generation NVDEC, up to 12 concurrent
encode sessions, H.264/HEVC/AV1 encoding, and a much broader decode/profile
matrix. That is a hardware capability list, not Linux qualification.

On this P16, `/dev/video0`–`3` are the internal ASUS RGB/IR USB cameras;
`/dev/video4`–`5` belong to a Logitech StreamCam when attached. None is an NVENC
or NVDEC node. `libnvidia-encode.so`, `libnvcuvid.so`, and
`libva-nvidia-driver` are installed. The current distribution FFmpeg has VA-API
but no `*_nvenc` encoders or `*_cuvid` decoders. A bounded H.264 VA-API/NVDEC
probe decoded 10/10 frames using the direct backend; it does not qualify other
codecs, applications, encoding, performance, or resume. The existing
[hardware overview](README.md#hardware-enablement-in-this-project) and
[inventory tool](scripts/platform-inventory.py) remain the machine record.

Other N1X laptop designs may use an ACPI-described MIPI/CSI camera receiver,
ISP, camera control unit, and sensors. A [firsthand Lenovo Pro 9
inventory](https://github.com/omacom/omarchy/discussions/16511) reports
`NVDA2800`–`2803`, `NVDA2808`, `NVDA2810`/`2812`, and `NVDA2820` without a
matching capture stack. Those IDs are absent on this P16. P16 USB camera tests
cannot qualify that separate platform pipeline.

| Track | Current evidence | Required end state |
| --- | --- | --- |
| NVDEC | H.264, HEVC and AV1 8-bit plus HEVC/AV1 10-bit, HEVC RExt 12-bit 4:2:0 and 4:4:4, VP9 8/10/12-bit, VP8, MPEG-2 and MJPEG samples pass through tested hardware paths; HEVC 4:4:4 8/10/12-bit and 4:2:2 8/10/12-bit plus H.264 High 4:2:2 8/10-bit CUVID pixels match software; H.264 High 4:4:4 8/10-bit is explicitly unsupported by CUVID; installed mpv uses H.264 VA-API and HEVC 4:4:4 Vulkan Video decode; installed FFplay uses CUVID plus libplacebo/Vulkan for 4:2:2 without observed chroma downsampling. Google Chrome 156 uses VA-API for short H.264, VP9 and AV1 1280×720 tests with the installed P16 launcher, while Arch ARM Chromium 156 fell back to software in the H.264 test. An NVRM allocation warning occurred during the first AV1 run; the identical repeat was clean | Advertised format/profile cases tested where supported; browser and desktop playback, plus boot/resume, demonstrably use hardware decode |
| NVENC | Isolated ARM64 FFmpeg package installed; H.264, HEVC and AV1 NVENC sessions all fail with error 21 on driver 615.78.08 using either API 12.2 or 13.1 codec headers. Vulkan Video H.264/HEVC/AV1 8-bit plus HEVC/AV1 10-bit encoding works through a different API. The live RGB camera has recordings through FFmpeg, GStreamer and an installed OBS→NUT→Vulkan H.264/AAC bridge. AV1 Vulkan default/inter-frame output decodes but loses fidelity: the same 120 real camera frames score 31.89 dB with default GOP and 53.80 dB all-intra. Explicit 10–40 Mbit/s targets also fail delayed decode in 30-second camera runs. An all-intra AV1 candidate gives 905/905 independently decoded live camera frames from an extracted package; installation remains pending. This does not change the NVENC error. | A packaged Linux NVENC encoder path, verified H.264/HEVC/AV1 outputs, and an actual recording or stream using NVENC |
| GPU video effects | Installed mpv/libplacebo Vulkan scaling and interpolation exercised in playback. The P16 OLED carries actual HDR10 HEVC playback through Vulkan decode, 10-bit Hyprland output and nonzero DRM HDR metadata. Installed NVOFA commands provide Linux video motion analysis and source-resolution midpoint export with Vulkan Video H.264: controlled translations at 320×180 and 1280×720, timed A/V, full-resolution P16 camera export and mpv playback pass. A moving-foreground occlusion fixture beats crossfade but retains boundary error. A 20-second live camera export passed at 1280×720/60 fps. Four 120-second runs missed eight, 14, four and 15 camera input frames respectively, while exporting every captured pair correctly. Human visual quality and hours-long performance remain open | Each selected effect runs through a supported Linux implementation and is consumed by a real application; visual quality, SDR-to-HDR conversion and unsupported vendor SDK features remain explicitly open |
| P16 USB cameras | RGB and IR live capture passes; RGB and IR preview in installed mpv, RGB Chromium WebRTC with graphical permission, OBS recording through x264 and an installed H.264 Vulkan/AAC bridge, and a GTK/libportal 30-frame PipeWire portal capture pass. The IR mpv preview renders 360×360 gray with advancing frames and successful camera reopen, but logs V4L2 buffer warnings on close. The bridge's camera/tone test had 21 ms A/V end difference. UVC privacy is read-only at 0; the owner reports no physical shutter. An installed Linux USB authorization switch passed off/on and post-restore application tests. Kernel37 exposed overlarge internal and external UVC DMA allocations; native kernel38 caps internal RGB allocations at 65,536 bytes with clean RGB/IR capture. External StreamCam capture also passed 60 frames without a new warning; its kernel38 URB size still needs a trace. | Electronic privacy/LED behavior, warning-free UVC allocation on both hosts, and post-resume capture tested independently |
| N1X MIPI/CSI cameras | Reported on other laptop models, absent here | On each affected model: upstreamable sensor/receiver/ISP stack, libcamera/desktop integration, and successful physical capture |

### Implementation record, 18 November 2026

The repeatable bounded corpus is [`scripts/check-n1x-media.py`](scripts/check-n1x-media.py),
the isolated NVENC candidate is [`platform/video/PKGBUILD`](platform/video/PKGBUILD),
and the [raw media evidence](docs/evidence/n1x-media-20261118/README.md)
contains the machine record, codec outputs, camera results and normal-app
playback/recording logs. The corpus exits nonzero while NVENC fails. A Vulkan
Video encode result is recorded separately and must not be relabelled NVENC.
The candidate's direct H.264, HEVC and AV1 CUVID decode paths pass their
bounded workloads, including HEVC and AV1 10-bit cases.
An isolated x265 4.3 build generated a valid 12-bit HEVC RExt fixture.
[`check-hevc12-nvdec.py`](scripts/check-hevc12-nvdec.py) confirms 30 CUVID
frames with pixel hashes matching software decode and 30 VA-API hardware
frames. The installed `p16-video-play` command reaches VA-API `p012` output
through `gpu-next` and finishes the bounded stream. The raw fixture has no
timestamps, so frame pacing and audio sync remain unqualified. A separate
[12-bit VA-API readback](docs/evidence/n1x-media-20261118/hevc12-vaapi-readback-kernel38.md)
now downloads 30 `p012le` hardware frames with `-threads 1` and finds every
output byte equal to software decode. Default-thread readback stalled after
seven frames; that path remains open.
The same test now covers HEVC 4:4:4 12-bit: CUVID again matches all software
frame hashes, and installed mpv reaches EOF with explicit Vulkan Video decode
and a `p412` renderer surface. The distribution FFmpeg's VA-API bridge decodes
the stream but offers no usable 16-bit readback. Forced `yuv444p` completes
30 frames with incorrect pixel bytes; it must not be used for this profile.
An isolated [Q416-mapped FFmpeg candidate](docs/evidence/n1x-media-20261118/hevc444-vaapi-readback.md)
downloads 30 `yuv444p16le` hardware frames with `-threads 1`; all 10,368,000
bytes equal software output for both 10-bit and 12-bit HEVC RExt 4:4:4. Its [patch](platform/video/0001-vaapi-map-q416-planar-16bit-444.patch)
is in the reproducible package recipe. A [timed FFplay application test](docs/evidence/n1x-media-20261118/hevc44412-vaapi-player-kernel38/hevc44412-vaapi-playback.json)
reached the end of a three-second 12-bit 4:4:4 clip using both CUVID and
VA-API decode with the Vulkan renderer. The renderer received `vaapi` frames
in both the installed 9.0.2-5 player and the extracted 9.0.2-6 package
player. This playback path already works on 9.0.2-5; the Q416 patch
specifically enables correct FFmpeg 16-bit VA-API readback. Extracted package
9.0.2-7 repeats both 10- and 12-bit readback and timed playback successfully;
installation and installed-package readback remain pending. Physical display
precision, color accuracy and zero-copy behavior remain unmeasured.
The [VA-API capability query](docs/evidence/n1x-media-20261118/vainfo-nvidia.log)
lists Main12 and Main444 8/10/12-bit decode entrypoints. The installed
distribution FFmpeg's [8-bit Main444 VA-API readback](docs/evidence/n1x-media-20261118/hevc4448-vaapi-readback-kernel38.json)
matches all 30 software frames byte-for-byte. Other advertised profiles
still need their own output tests.
The [HEVC pro-format matrix](docs/evidence/n1x-media-20261118/hevc-pro-matrix.json)
also verifies 4:4:4 8/10-bit hardware playback (`nv24`/`p410`) and direct CUVID
pixel equality for 4:2:2 8/10/12-bit. VA-API has no 4:2:2 entrypoint here;
FFmpeg's zero exit status masked a decoder initialization failure and software
fallback. Mpv's requested Vulkan path likewise fell back to software for all
three 4:2:2 cases. The installed [`ffplay-n1x`](platform/video/PKGBUILD)
package opens all three 4:2:2 fixtures with `hevc_cuvid`. Its previous SDL
renderer converted them to `IYUV` 4:2:0, as the [older installed matrix](docs/evidence/n1x-media-20261118/installed-ffplay/hevc-pro-matrix.json)
shows. Version 9.0.2-5 enables its existing libplacebo/Vulkan renderer. The
[new installed matrix](docs/evidence/n1x-media-20261118/installed-ffplay-vulkan/hevc-pro-matrix.json)
shows CUVID pixel equality with software and renderer input formats `nv16`,
`p210le` and `p212le` for 8, 10 and 12 bits. No intermediate 4:2:0 conversion
is logged. The actual display's output bit depth and color accuracy remain
unmeasured.
The [H.264 pro-format matrix](docs/evidence/n1x-media-20261118/installed-h264-pro-kernel38/h264-pro-matrix.json)
adds High 4:2:2 at 8/10 bits: CUVID returns 30 frames byte-identical to
software (`nv16`/`p210le`), and the installed FFplay Vulkan player takes both
timed clips to EOF with those surfaces entering libplacebo. High 4:4:4
Predictive at 8/10 bits is explicitly rejected by CUVID's capability query.
For all four H.264 pro formats, a requested VA-API decode exits 0 through
software, without `vaapi` frames; the installed VA-API driver advertises no
corresponding H.264 profiles. These negative cases are recorded as skips,
not hardware passes.
The [timed 4:2:2 player test](scripts/check-hevc422-av-playback.py) additionally
played a six-second Matroska HEVC 4:2:2/AAC clip through the installed Vulkan
player. It opened `hevc_cuvid` on `nv16`, processed the audio stream, and
reached EOF in real time; 184 A/V status samples had at most 27 ms clock
offset. Package 9.0.2-5 was installed through graphical Polkit authentication
without replacing distribution FFmpeg; its FFplay SHA256 matches the tested
package archive. The [Vulkan renderer record](docs/evidence/n1x-media-20261118/ffplay-vulkan.md)
contains build and test identities.
During the older 9.0.2-4 HEVC matrix, two NVRM `NV_ERR_NO_MEMORY` allocation
warnings appeared while mpv played the 4:4:4 10-bit sample. A targeted
[repeat](docs/evidence/n1x-media-20261118/nvrm-memory-warning.md) passed
without another warning. The bounded 9.0.2-5 matrix produced no new NVRM or
Xid lines, but longer and concurrent stability is not qualified.
The [NVENC API-version comparison](docs/evidence/n1x-media-20261118/nvenc-api-version-compare.json)
uses identical FFmpeg 9.0.2 sources with pinned NVIDIA codec headers 12.2 and
13.1. All three NVENC codecs fail at `OpenEncodeSessionEx` with error 21 on
both builds; a header downgrade alone does not enable the session.
The [latest installed binary check](docs/evidence/n1x-media-20261118/installed-nvenc-vulkan/installed-nvenc.json)
repeats H.264, HEVC and AV1 through `/usr/bin/ffmpeg-n1x` from package
9.0.2-5. All three still fail at session creation with error 21. Both tested SDK
headers [name that status](docs/evidence/n1x-media-20261118/nvenc-status-21.md)
`NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY`; the name alone does not establish the
driver's cause. Enabling the Vulkan renderer did not change the NVENC result.
An independent [CUDA/NVENC C probe](scripts/probe-nvenc-session.c) also reaches
`NvEncodeAPICreateInstance` successfully with API 12.2 and 13.1, but
`NvEncOpenEncodeSessionEx` returns 21 for both. This reproduces the failure
without FFmpeg; the cause within the installed driver/platform remains unknown.
An [EGL/OpenGL NVENC session probe](docs/evidence/n1x-media-20261118/nvenc-opengl-session.md)
also opened a real N1X GL context and returned 21 for both API header sets.
Thus switching the API device type does not bypass this driver failure.
NVIDIA's aarch64 620.70.06 release lists the P16's N1X PCI ID `2E03`, but
NVENC on that version is untested here; the currently running stack remains
615.78.08. A separate ARM64 RTX 5050 report suggests a 615 driver regression,
but it does not prove the N1X's cause or a 620 fix.
The [620.70.06 offline audit](docs/evidence/n1x-media-20261118/nvenc-620-offline.md)
checks NVIDIA's archive SHA256, applies all three local DRM/PM/UVM patches
without fuzz, and builds five modules with matching kernel36 `vermagic`.
The ARM64 distribution's matching 620 utils and DKMS archives are now
downloaded with valid package signatures. No 620 module was loaded and the
615 userspace/firmware stack remains installed. Five 620 modules now also
[build against kernel38](docs/evidence/n1x-media-20261118/nvenc-620-offline.md#matched-kernel38-offline-build)
with matching `vermagic` and BTF. Versioned dependencies require an isolated
620 root/boot candidate with a proven 615 rollback, followed by native
display, suspend/resume and NVENC session/output tests.
The [isolated-root staging procedure](docs/evidence/nvidia620-isolated-root-staging.md)
pins the Btrfs snapshot, package, candidate UKI and rollback checks needed
before a native 620 boot. A [copied Pacman database transaction](docs/evidence/nvidia620-pacman-db-transaction-20261118.json)
accepts the six-package 615 removal and four-package 620 installation with
matched 620 versions, without changing the live root. File installation,
hooks and UKI are outside that database-only simulation. A
[full-payload fakeroot repeat](docs/evidence/nvidia620-pacman-payload-transaction-20261118.json)
extracted all 4,281 candidate files into a disposable partial root, found all
13 kernel38 modules and passed `pacman -Qkk` for the four new packages with
zero altered files; the live 615 versions stayed unchanged. It still does
not test the actual snapshot, hooks or UKI. A second
[disposable `--sysroot` transaction](docs/evidence/nvidia620-pacman-sysroot-transaction-20261118.json)
passed the same payload and `pacman -Qkk` gates using Pacman's intended
mounted-guest mode; it used a minimal test config, so signed-archive
verification remains a separate gate. A [read-only file collision audit](docs/evidence/nvidia620-file-collisions-20261118.json)
found 4,281 candidate files with zero unexpected package or unowned-path
overlaps. The candidate root and UKI have not yet been created.
The [snapshot helper](scripts/stage-nvidia620-snapshot.py) passes its
read-only Btrfs/EFI/package preflight but currently refuses staging while
the graphical media-package transaction waits. Its privileged snapshot
mode has not been run.
The [candidate package-stage helper](scripts/stage-nvidia620-packages.py)
is prepared with `pacman --sysroot`, candidate-only hook masking, explicit
`depmod`, and live-package/EFI checks; its root stage mode has not run.
A later CUDA/UVM fault on the running 615/kernel36 stack produced a recursive
`mmap_lock` Lockdep warning. The [MMU notifier candidate and three EFI/KVM
cases](docs/evidence/mmu-notifier-lockdep-20261118.md) reproduce the warning
with the original Image and keep Lockdep active with a small kernel-core
correction. That correction is present in the running kernel37 native boot;
post-resume use remains unqualified.
The [complete kernel37 offline bundle](docs/evidence/kernel37-offline-20261118.md)
packages that correction with matched 615.78.08 platform modules. Seven fresh
EFI/KVM cases and all 8,507 split-BTF module checks pass against its final
Image. The [native boot record](docs/evidence/kernel37-native-20261118.md)
confirms working NVIDIA display and RGB/IR camera capture. H.264, HEVC and AV1
NVENC still fail at session open with error 21. Internal RGB capture triggered
a DMA-debug warning, so clean-boot and physical suspend qualification remain
open.
Kernel37 is installed as an additional [verified boot entry](docs/evidence/kernel37-staged-20261118.md),
with its 13 production modules hash-matched after the generic DKMS hook and
its UKI checked against the installed SPI HID bytes. Kernel37 was tested
through a one-time UEFI boot entry; kernel36 remains the Limine default.
Native kernel37 results are recorded separately from staging.
The [kernel38 candidate was staged](docs/evidence/kernel38-staged-20261118.md)
with the UVC DMA cap, matching 615 driver package, 13 hash-matched production
modules and a rebuilt initial UKI whose embedded SPI HID modules match disk. Its
8,504 installed and 430 initramfs modules passed BTF verification. Limine
still defaults to kernel36. Its [first native boot](docs/evidence/kernel38-native-20261118.md)
has working NVIDIA display and RGB/IR capture with capped DMA allocations,
and no new kernel warning. NVENC remains at error 21 on the running 615 stack.
The first kernel38 UKI omitted the known-good audio DSP flags, so the generic
SOF placeholder bound instead of `n1x_adsp`; an audio-enabled UKI is now
staged for a later qualified boot. Physical suspend and matched 620 runtime
remain open.
The OBS camera recording used the existing V4L2 interface and the x264
software encoder; it proves application camera use, not hardware encode.
A separate FFmpeg recording used the live RGB camera with NVIDIA Vulkan Video
H.264 hardware encode and independently verified 60 frames. OBS's direct
advanced FFmpeg output failed to open `h264_vulkan` with `Invalid argument`.
The [live AV1 Vulkan capture](docs/evidence/n1x-media-20261118/camera-av1-vulkan.md)
also encoded 60 distinct real camera frames, checked against both libdav1d
and libaom. `-fps_mode passthrough` was required to avoid FFmpeg duplicating
slow camera frames. With the camera's original dynamic exposure frame-rate
setting, 60 input frames spanned 5.9 seconds; temporarily disabling that
control yielded a 1.967-second PTS span, then restored its original value.
This is a bounded default-rate-control Vulkan Video bitstream result, not an
NVENC or visually qualified application result. Longer camera runs found
delayed decode failure at explicit 10–40 Mbit/s targets. A frame-aligned
quality test found severe inter-frame AV1 drift despite complete decode;
libdav1d and libaom produce byte-identical pixels in the synthetic cases, so
this is not a single-decoder artifact. An all-intra GOP removes the drift on
this driver. The [same-source real-camera comparison](docs/evidence/n1x-media-20261118/vulkan-encode-quality-camera-kernel38.json)
also measures 31.89 dB at the default GOP versus 53.80 dB all-intra across
120 captured frames, with both AV1 decoders yielding byte-identical pixels.
The exact fault layer remains open.
The installed [`p16-record-obs-vulkan`](platform/video/tools/README.md) bridge
instead receives OBS's raw NUT output through a private Linux FIFO and uses
FFmpeg's explicit Vulkan device and `hwupload` path. A real camera plus a
generated tone recorded 208 distinct 1280×720 frames with H.264/AAC;
independent decode passed and video/audio packet ends differed by 21 ms.
The [bridge record](docs/evidence/n1x-media-20261118/obs-vulkan-bridge.md)
pins the application and package result. Direct in-process OBS Vulkan
encoding and longer or post-resume use remain open. Neither Vulkan path
proves NVENC API use.
GStreamer 1.28.8 exposes `vulkanh264enc` for the N1X. The installed
`p16-record-camera-gstreamer` command connects the P16's real MJPEG camera
through FFmpeg's MJPEG decode and NV12 conversion to GStreamer's `rawvideoparse`,
`vulkanupload` and `vulkanh264enc`. The [installed test](scripts/check-p16-gstreamer-camera.py)
independently decoded 60 H.264 1280×720 frames; all 60 downscaled frame hashes
were distinct. The elementary stream was then deleted. This qualifies a
second Linux media framework's Vulkan hardware encoder in a real recording,
but does not change the NVENC API or direct OBS encoder failure.
The [`p16-media-tools` package](platform/video/tools/README.md) provides explicit
mpv hardware playback, on-demand HDR10 output and P16 RGB/Vulkan recording
commands without replacing system codecs. Version 0.1.0-7 is installed on the
reference P16: the installed
mpv command played through VA-API and Vulkan/libplacebo to EOF, and the
installed recording command produced a 60-frame H.264 file from the live RGB
camera. The temporary footage was deleted after independent probing. This
qualifies those specific Linux workflows on this machine; it does not close
NVENC, direct in-process OBS Vulkan encoding or power-management gates.
The 0.1.0-9 package candidate adds an AV1 mode and passthrough timestamps to
the camera recording command. Its [short extracted-package test](docs/evidence/n1x-media-20261118/camera-av1-packaged-candidate.json)
passed two-second H.264 and AV1 recordings with 60 distinct frames each.
A [30-second AV1 timing test](docs/evidence/n1x-media-20261118/camera-av1-vulkan.md#thirty-second-camera-timing-and-package-correction)
then exposed eight non-increasing packet PTS values in that candidate.
Package candidate 0.1.0-10 uses the camera's microsecond encoder time base;
its 30-second run has 905 strictly increasing packets, 905 distinct libdav1d
frames, 905 libaom frames and restored camera control. FFmpeg read one
additional input frame at the `-t 30` boundary, so strict retention of every
read input is not claimed. The [frame-aligned quality and real-camera
tests](docs/evidence/n1x-media-20261118/av1-vulkan-ratecontrol.md#longer-real-camera-and-visual-quality-gates)
then exposed severe inter-frame AV1 quality drift. Candidate 0.1.0-11 adds
all-intra GOP 1 only for AV1; its exact extracted package command produced
905 monotonic camera frames and both libdav1d and libaom decoded all 905.
Synthetic PSNR rose from 19.81 dB at the default GOP to 63.74 dB all-intra.
The candidate still requires installation and a repeat through
`/usr/bin/p16-record-camera-vulkan`; subjective quality and post-resume use
remain open.
The [HDR output test](scripts/check-p16-hdr-output.py) then played a 10-bit
PQ/BT.2020 HEVC stream with the installed `p16-hdr-play` command on the internal
Samsung OLED. Mpv selected Vulkan hardware decode and an HDR10 ST2084 surface;
Hyprland selected `XBGR2101010/hdr`, and NVIDIA DRM reported BT.2020 RGB
Colorspace 9 and nonzero HDR metadata. After mpv quit, the display returned to
`XRGB8888/srgb`, Colorspace 0 and zero metadata. A separate SIGKILL test of the
launcher confirmed that its watchdog closes mpv and restores SDR. The
[evidence record](docs/evidence/n1x-media-20261118/hdr-output.md) includes the
internal panel's EDID capabilities and test outputs. This qualifies the Linux
HDR10 transport and application path, not measured luminance, color accuracy,
SDR-to-HDR conversion or NVIDIA TrueHDR.
The [interactive A/V playback test](scripts/check-n1x-av-playback.py) uses a
24-second H.264/AAC fixture in that installed player. It confirms VA-API
decoding, Vulkan rendering, PipeWire audio, forward/backward seeks, a stable
pause, resumed playback and EOF. Sampled mpv audio/video clocks differed by
at most 22 ms during playback after those operations. This is a bounded
clock/interaction check, not a human listening test or a long playback run.
The [media resume preflight](docs/evidence/n1x-media-resume-20261118/README.md)
stopped before sleep: ACPI TAD RTC1 returned `Input/output error` and EFI RTC0
returned `Invalid argument` when asked to arm a wake alarm. NVIDIA kernel
suspend notifiers are active and the verified VT handoff must be preserved.
No after-resume media result is claimed.
The initial [Chromium decode check](docs/evidence/n1x-media-20261118/browser-decode.json)
used a 320×180 H.264 fixture and reported `FFmpegVideoDecoder` with
`kIsPlatformVideoDecoder=false`. Chrome 156 did likewise on that small fixture.
At 1280×720, Google Chrome 156 with the same NVIDIA VA-API flags reported
`VaapiVideoDecoder` and `kIsPlatformVideoDecoder=true` for all 96 frames with
no drops. The `p16-video-chrome` launcher also selected that path in an
isolated profile. The installed launcher then passed the same 96-frame,
1280×720 check with VP9 and AV1. A concurrent NVRM allocation warning was
logged during the first AV1 run; an identical repeat passed without a new
kernel warning. A later 20-second AV1 playback passed 480 frames without
drops or a concurrent kernel warning. The [AV1 Vulkan rate-control check](docs/evidence/n1x-media-20261118/av1-vulkan-ratecontrol.md)
separately shows invalid output from explicit bitrate and QP modes, so the
browser fixture was generated with `aomenc` and independently decoded first.
[Browser evidence](docs/evidence/n1x-media-20261118/browser-vaapi.md)
includes the flags, negative controls and upstream references. Arch ARM
Chromium 156 still selected `FFmpegVideoDecoder` at 1280×720 even with the
extended flags. HEVC and deeper browser profiles, real sites, longer or
concurrent playback, other resolutions and post-resume playback remain open.
The [P16 RGB camera contention test](scripts/check-p16-camera-contention.py)
holds a 120-frame V4L2 capture, observes `Device or resource busy` from a
second client, then captures 10 frames after release.
The [GTK/libportal application test](scripts/check-p16-camera-portal.py)
obtained graphical camera permission, opened the portal PipeWire remote,
enumerated the exposed camera nodes, and captured 30 MJPEG buffers from the
internal RGB camera. GStreamer required `media.type=Video`,
`media.category=Capture`, and `media.role=Camera` on its stream; without them,
WirePlumber reported `target not found` even though the node was visible.
The [result](docs/evidence/n1x-media-20261118/camera-portal.json) records
1280×720/30 caps, varying nonzero buffer sizes, EOS, and no retained pixels.
This qualifies the Linux camera portal and PipeWire capture path for a native
GTK application. A sandboxed Flatpak consumer, permission denial/revocation,
and a post-resume repeat remain open.
Chromium's [graphical WebRTC camera test](docs/evidence/n1x-media-20261118/browser-camera-graphical.json)
also passed after the user approved its real permission prompt. With a fresh
temporary browser profile and no fake media or permission-UI flags, it selected
`ASUS FHD webcam`, negotiated 1280×720/30, and sampled 30 varying preview
frames without retaining pixels. That browser test is separate from the GTK
PipeWire portal test.
The [P16 UVC privacy test](docs/evidence/n1x-media-20261118/camera-privacy-control.json)
then confirmed a read-only `privacy=0` control. A write to privacy failed while
writing the current brightness value succeeded; the camera continued producing
30 frames. The owner reports no physical shutter. The installed
[`p16-camera-privacy`](platform/video/tools/README.md) command uses standard
Linux USB authorization on the exact internal camera device. Its
[self-test](docs/evidence/n1x-media-20261118/camera-privacy-switch.json) removed
all four V4L2 nodes at `authorized=0`, restored them at 1 and then passed
unprivileged V4L2 and Chromium capture. This is a software privacy mechanism;
it must not be described as a hardware shutter. Its state may reset after
reboot or device re-enumeration.
The [installed mpv IR preview check](docs/evidence/n1x-media-20261118/ir-mpv-preview-kernel38.json)
opens the separate 360×360 GREY camera through V4L2 and renders it in a
Wayland/Vulkan window. Nine positive playback-time samples advance by 1.599
seconds, the process exits normally through IPC, and a new FFmpeg capture
reopens the camera. Mpv logs a V4L2 owned-buffer warning and 17 QBUF attempts
after close; the successful reopen prevents treating that as a stuck device,
but the clean-shutdown gate is open. No IR pixels or recording are retained.
This is a usable preview path, not biometric face-authentication support or
subjective image-quality acceptance.
The [StreamCam UVC trace](docs/evidence/n1x-media-20261118/uvc-streamcam-urb-size-current-boot.json)
attributes the earlier 98,304/65,536 DMA-debug warning to an exact
`32 × 3,072`-byte URB on host `NVDA8000:00`. A separate
[internal-camera trace](docs/evidence/n1x-media-20261118/uvc-urb-size-current-boot.json)
records the ASUS RGB/IR URBs on `NVDA8001:00`; those cameras did not cause the
earlier external-host warning. On a fresh kernel37 boot, internal RGB capture
produced its own 94,208/65,536-byte warning on `NVDA8001:00`. A small UVC
buffer-limit patch [passed a live kernel37 module test](docs/evidence/n1x-media-20261118/uvc-dma-live-kernel37.md)
for RGB, IR and GStreamer/Vulkan capture without a new DMA warning. The
[kernel38 bundle](docs/evidence/kernel38-offline-20261118.md) packages that
UVC fix with matching 615.78.08 platform modules. Its packaged Image passed
a direct KVM boot, and all 8,507 modules passed BTF validation. The
[first native boot](docs/evidence/kernel38-native-20261118.md) captured RGB
and IR frames with capped internal RGB allocations and no new warning. A
[separate StreamCam capture](docs/evidence/kernel38-uvc-streamcam-native-20261118.json)
passed 60 frames at 1080p without a new warning. External URB sizing and
physical suspend remain open. A [single-auth UVC trace wrapper](scripts/run-p16-uvc-dma-trace.py)
is prepared to measure internal and external URBs and restore trace state on
the current boot, without another reboot.

## Common evidence and release gates

1. Before changes, record DMI model, BIOS, ACPI IDs, `uname -a`, kernel/module
   hashes, `nvidia-smi`, `pacman -Q`, FFmpeg build configuration, GPU and video
   device nodes, `v4l2-ctl --list-devices`, and relevant kernel errors. Use
   `scripts/platform-inventory.py` without `--capture-acpi` for the routine
   read-only record. Save each candidate result in `docs/evidence/` with the
   exact package/source identities and raw command logs; redact unrelated
   private camera content.
2. Keep the known-working boot entry and packages. Build candidate FFmpeg,
   libraries, or kernel modules as reproducible packages with pinned sources,
   checksums, licenses, and matching NVIDIA userspace/driver versions. Do not
   replace the working stack merely because it compiles. Track proposed
   Omarchy package changes separately from local qualification.
3. Test a short, deterministic workload first. Reject driver faults, hangs,
   memory corruption, wrong output, or new kernel warnings before longer runs.
   Record return codes, output hashes/metadata, frame counts, GPU/video-engine
   observations, elapsed time, power profile, and temperature. A counter alone
   is insufficient: require logs or API evidence that the intended hardware
   path was selected and correct decoded or encoded output.
4. Repeat the accepted workload after application restart, a fresh boot, and
   a physical s2idle/resume cycle on the exact candidate. Verify that normal
   desktop playback/capture still works. Keep device-only PM, physical sleep,
   and long repeated sleep as distinct results.
5. A track is **used** only when a normal Linux application reaches it through
   its documented interface without a private debug ioctl or forced device
   binding. Record the application's settings, selected backend, a real output
   or visible playback/capture, and a negative/control run that distinguishes
   hardware use from silent software fallback.

## 1. Codec engines: NVDEC and NVENC

### Discover and package the Linux path

1. Compare the exact GPU against NVIDIA's linked matrix. Enumerate decoder
   profiles with `vainfo --display drm --device /dev/dri/renderD128` after
   installing the diagnostic tool, using `LIBVA_DRIVER_NAME=nvidia` and the
   tested backend. Query NVENC capabilities through the Video Codec SDK or
   an FFmpeg build that includes NVENC. Treat a missing profile as an explicit
   skipped capability, not as proof the whole engine is absent.
2. Keep NVDEC's VA-API path as a conventional Linux media interface. Verify
   its frame surfaces and hardware selection with FFmpeg verbose logs. The
   installed [NVIDIA VA-API bridge](https://github.com/elFarto/nvidia-vaapi-driver)
   implements decoding only; do not route NVENC through `h264_vaapi` or claim
   that VA-API encoder enumeration proves NVIDIA encoding.
3. Package an ARM64 FFmpeg build with a compatible `nv-codec-headers` snapshot,
   `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, and CUDA/NVDEC integration according
   to the [NVIDIA FFmpeg guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/).
   Preserve ordinary software codecs and distribution ABI compatibility. Test
   the built package in an isolated install before making it the Omarchy
   default. `ffmpeg -encoders`, `ffmpeg -decoders`, and `ffmpeg -hwaccels` are
   discovery checks only; a successful encode/decode is required.
4. If using PyNvVideoCodec or GStreamer instead, pin an ARM64 artifact with
   explicit Linux N1X compatibility and demonstrate the same runtime contract.
   A DGX Spark or Windows ARM64 support statement is not by itself a P16 Linux
   result. Do not add a second kernel codec driver for functionality already
   provided by the NVIDIA driver without a demonstrated missing Linux ABI.

### Test matrix and acceptance

The first executable smoke checks use generated frames and write no lasting
video file. Run them with logs captured in the evidence record; replace the
format/profile and source fixture only after the baseline passes. The first
command confirms the existing decode path; the second requires the new FFmpeg
package and must fail explicitly if `h264_nvenc` is unavailable:

```sh
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=320x180:rate=10 -frames:v 10 -c:v libx264 -f h264 - |
  env LIBVA_DRIVER_NAME=nvidia NVD_BACKEND=direct \
  ffmpeg -hide_banner -loglevel verbose -hwaccel vaapi \
    -hwaccel_device /dev/dri/renderD128 -f h264 -i pipe:0 \
    -frames:v 10 -f null -

ffmpeg -hide_banner -f lavfi -i testsrc2=size=320x180:rate=10 \
  -frames:v 10 -c:v h264_nvenc -f h264 - |
  ffmpeg -hide_banner -f h264 -i pipe:0 -frames:v 10 -f null -
```

Keep the full FFmpeg logs: a zero exit status from a generic decoder after an
NVENC encode does not by itself prove that NVDEC was used on the second leg.
For an end-to-end GPU transcode, select and verify the decoder explicitly.

| Test set | Workload | Pass evidence |
| --- | --- | --- |
| Decode baseline | H.264 8-bit 4:2:0, HEVC 8/10-bit, AV1 8/10-bit | Complete frame count, correct dimensions/timestamps, no decode errors, selected NVDEC path, compared against software reference |
| Pro formats | Supported H.264/HEVC 4:2:2 and 4:4:4, HEVC 12-bit, and advertised legacy/VP9 profiles | Capability query first; representative licensed/generated fixtures; bit depth, chroma, color metadata, and output validated per case |
| Encode baseline | Generated color bars and motion into H.264, HEVC, AV1 | NVENC session created, resulting bitstream decodes independently, frame count/timestamps and codec/profile/level/color metadata correct |
| Encode advanced | 10-bit, 4:2:2/4:4:4, HEVC 8K, lossless where the exact N1X query permits | Short bounded clips; capability-specific settings and objective quality/round-trip checks; unsupported combinations explicitly recorded |
| Pipelines | Decode → scale/color convert → encode, plus concurrent sessions up to the reported limit | Correct outputs and no leaks/stalls; sustained throughput, latency, power and temperature recorded; no claim that 12 sessions means 12 engines |
| Recovery | Reopen, application crash/restart, fresh boot, physical resume | Repeated outputs and clean driver/log state; no silent CPU fallback |

Use generated test patterns or redistributable fixtures with fixed revisions.
Lossy output is checked with decoded frame counts, timestamps and appropriate
quality metrics; byte-identical compressed output is not required. For HDR and
10/12-bit cases, validate transfer function, primaries, range and bit depth as
well as pixels. Do not infer an 8K or 4:2:2 Linux success from a low-resolution
H.264 decode.

The end-user gate is a real desktop playback case (for example a player using
the validated VA-API backend) and a recording or stream in a normal application
(for example OBS using the packaged NVENC backend). Confirm hardware activity
through backend logs plus NVIDIA video-engine telemetry where available;
compare with an intentionally software-decoded/encoded control. Check audio
sync, seeking, pause/resume, frame drops and output playback. Browser decode
is a separate gate because browser sandbox and DMABUF/Wayland behavior may
differ from FFmpeg. Do not mark it complete from a command-line result.

## 2. Video effects and image processing

Treat codec engines, CUDA/Vulkan image processing, and a camera ISP as different
subsystems. NVIDIA advertises Video Super Resolution, Video Frame Generation,
and TrueHDR for RTX Spark through its
[AI for Media SDKs](https://developer.nvidia.com/blog/code-test-and-deploy-on-one-machine-with-nvidia-rtx-spark/).
The [Linux Video Effects SDK requirements](https://docs.nvidia.com/maxine/vfx/latest/LinuxVFXSDK/GetStartedonLinux.html)
describe a server deployment and the [Linux package list](https://docs.nvidia.com/maxine/vfx/latest/LinuxVFXSDK/InstalltheVFXSDK.html)
does not list N1X/GB10. Do not treat the Windows ARM64 SDK or a Blackwell
architecture label as an approved Linux ARM64 client package.

The internal `ATNA60HC05-0` OLED advertises BT.2020 RGB, ST2084/PQ and HDR
static metadata in EDID. The installed `p16-hdr-play` uses Hyprland's
on-demand 10-bit HDR monitor mode and mpv/libplacebo Vulkan output for real
HDR10 HEVC content. The [bounded application test](docs/evidence/n1x-media-20261118/hdr-output.md)
verifies mpv's HDR10 swapchain, DRM BT.2020 RGB and nonzero HDR metadata, plus
normal-exit and SIGKILL restoration. The external U28E590's EDID does not
advertise HDR. The synthetic fixture verifies signaling and the playback path;
it is not a photometric quality pattern. Luminance, gamut accuracy, tone
mapping quality, long playback and proprietary TrueHDR remain open.

The separate [FFmpeg filter check](docs/evidence/n1x-media-20261118/ffmpeg-libplacebo-filter-kernel38.md)
found that its `libplacebo` Vulkan filter fails at initialization with the
installed API 360 library: FFmpeg's adapter rejects the N1X Vulkan queue flag
before a frame is processed. `scale_vulkan` processes a bounded frame on
the N1X. A [private API 387 candidate](docs/evidence/n1x-media-20261118/libplacebo-upscale-private.md)
processes 60 GPU frames. A [scoped API 360 queue-import patch and package 9.0.2-7](docs/evidence/n1x-media-20261118/libplacebo-api360-compat.md)
now process the same 60-frame tagged Spline36 test against the installed
libplacebo library; extracted-package Q416 readback and timed FFplay playback
also pass. Tagged GPU Spline36 still scores below CPU bicubic on this one
synthetic reference, and untagged raw input is markedly worse. The installed
mpv/libplacebo playback result stands separately. Package 9.0.2-7 installation,
explicit color tags in a normal export application, visual review and steady
latency remain open.

The [NVIDIA Optical Flow SDK](https://github.com/NVIDIA/NVIDIAOpticalFlowSDK)
CUDA API is usable on this N1X, independent of the NVENC session failure. The
installed [`p16-nvof-tools`](platform/video/nvof/README.md) package pins SDK
headers to commit `edb50da3cf849840d680249aa6dbef248ebce2ca`, compiles a
small CUDA API client and exposes `p16-optical-flow VIDEO [MAX_PAIRS]`. It
decodes ordinary video with FFmpeg and computes 4×4-grid optical flow on the
NVIDIA hardware for each frame pair. The [application test](docs/evidence/n1x-media-20261118/nvof-application.md)
measures approximately zero motion for identical textured frames, exactly
8-pixel horizontal flow for a controlled translation, and 30 frame pairs
from a temporary real P16 camera recording. The camera video was deleted.
This closes the NVOFA device/API and motion-analysis **used** gate. The
analysis command alone does not export frames or assert that NVIDIA's
proprietary Frame Generation SDK works on Linux ARM64.
The [installed midpoint export](docs/evidence/n1x-media-20261118/nvof-interpolation.md)
now uses forward and backward NVOFA vectors to generate intermediate frames,
then uses Vulkan Video H.264 encoding at source resolution. A deterministic
8-pixel translation produces the exact four-pixel midpoint at 320×180 and a
near-zero sampled error at 1280×720; a two-second
24 fps/AAC fixture exports 95 frames at 48 fps with a 16 ms audio/video end
offset. A live 60-frame P16 camera clip exports 119 frames at 1280×720/60 fps, decodes
independently and plays to EOF in mpv with hardware decoding. Both commands
from package `0.1.0-4` were re-tested after installation. Motion artifacts,
output quality, long exports and proprietary frame generation are unqualified.
A [moving-foreground occlusion control](docs/evidence/n1x-media-20261118/nvof-occlusion.json)
also uses the installed binary. Its nonperiodic moving texture yields midpoint
MSE 783 versus 2195 for crossfade, but local exposure-boundary errors remain.
This adds a controlled quality result without claiming subjective acceptance.
A [20-second installed-camera export](docs/evidence/n1x-media-20261118/nvof-20s-soak.json)
then processed 600 live source frames into 1199 H.264 1280×720/60 fps frames
in 33 seconds, with independent full-stream decoding and no new kernel GPU or
IOMMU faults. Temporary footage was deleted. Hours-long runs remain open.
The [120-second concurrent-build stress](docs/evidence/n1x-media-20261118/nvof-120s-concurrent-build.md)
recorded 3,592 of the expected 3,600 source frames; NVOFA and Vulkan exported
all 7,183 corresponding frames, but the exact capture-cadence gate failed.
The [mostly idle repeat](docs/evidence/n1x-media-20261118/nvof-120s-after-build.md)
recorded 3,586 source frames and exported all 7,171 corresponding frames;
its strict input-cadence gate also failed. A [third 120-second run with decoded
frame timing](docs/evidence/n1x-media-20261118/nvof-120s-frame-timing.md)
recorded 3,596 frames and found two 67/134-ms gaps accounting for its four
missing frames; NVOFA exported all 7,191 corresponding frames. The
[first native kernel38 repeat](docs/evidence/n1x-media-20261118/nvof-120s-kernel38.md)
recorded 3,585 source frames with 15 short timestamp gaps and exported all
7,169 corresponding frames. A [direct V4L2 cadence comparison](docs/evidence/n1x-media-20261118/camera-cadence-kernel38.md)
found a severe long-run slowdown with `exposure_dynamic_framerate=1` and a
much steadier stream with that control temporarily set to 0. A
[direct 3,600-buffer V4L2 run](docs/evidence/n1x-media-20261118/v4l2-sequence-kernel38.json)
then had no sequence or timestamp gap above 50 ms and no new kernel warning.
An independent [3,600-frame MJPEG decode](docs/evidence/n1x-media-20261118/mjpeg-decode-kernel38.json)
passed without a payload error, while its Null muxer logged 35 non-increasing
DTS warnings with passthrough timing.
The fixed-rate Vulkan output has 3,600 smooth encoded frames but FFmpeg
reports 16 output-rate drops; a 30-second passthrough run showed source
timestamp irregularities. That drop count must not be labeled USB packet
loss. Sporadic payload corruption in the earlier copy run and end-to-end
losslessness remain open.

1. For each effect, establish the documented Linux ARM64 artifact, supported
   GPU list, runtime/driver requirements, license and redistributability.
   If NVIDIA adds N1X support, package the exact SDK and its models, run its
   sample on this P16, then integrate an application through the published API.
2. Where that SDK is unavailable, choose a maintainable Linux implementation
   with a clear name and license. Vulkan/libplacebo scaling or tone mapping,
   and a separately selected CUDA/Vulkan/ONNX interpolation or super-resolution
   implementation, are candidates for equivalent functions. They are **not**
   claims that NVIDIA's proprietary VSR, Frame Generation, or TrueHDR ran.
   Package the selected filter/plugin and its model artifacts reproducibly.
3. For scaling, compare known source/output resolution, detail, temporal
   stability and latency against a disabled control. For frame interpolation,
   verify output frame count/PTS, motion artifacts, audio sync, and steady
   playback. For HDR conversion, verify HDR10 metadata and an actual HDR-capable
   DRM/KMS → compositor → display path; an offline HDR file alone does not
   establish desktop HDR output. Record visual review criteria and bounded
   GPU/power cost for each feature.
4. Demonstrate each accepted effect in a normal Linux workflow: playback or
   export through an installed media app, or a live OBS pipeline where relevant.
   A sample binary alone meets the API gate, not the **used** gate. If the
   display/compositor/SDK path cannot carry a feature, leave its desktop gate
   open and publish the precise blocker instead of enabling an inert toggle.

Optical flow and JPEG acceleration require device-specific capability and
runtime tests; library presence alone is insufficient. The NVOFA application
result above establishes an actual engine computation, while the nvJPEG
probe below establishes the absence of dedicated JPEG hardware in this runtime.
The [N1X nvJPEG capability probe](docs/evidence/n1x-media-20261118/nvjpeg-capability.json)
uses CUDA 13.4.2 on this P16. The default and GPU-hybrid handles report zero
dedicated JPEG decoder and encoder engines; the explicit hardware decoder and
encoder backends return `NVJPEG_STATUS_ARCH_MISMATCH` (7). This rules out a
dedicated nvJPEG hardware engine in the current runtime. The separate
[GPU-compute codec test](docs/evidence/n1x-media-20261118/nvjpeg-gpu-batch-kernel38.md)
decodes a 64-image baseline JPEG batch into CUDA memory and encodes one image
back to JPEG. Nsight observes GPU Huffman and encoder kernels; the decode has
62.15 dB PSNR and maximum channel error 2 against software, while the
independently decoded encode has 38.41 dB PSNR against its source. This
establishes GPU-compute JPEG decode and encode on native kernel38/615, not a
dedicated JPEG engine, application integration or post-resume result.

## 3. Cameras: P16 USB path and N1X MIPI/CSI path

### ASUS P16 H7607BA

1. Map each internal RGB/IR V4L2 node with `v4l2-ctl --list-devices`,
   `--all`, and `--list-formats-ext`; identify metadata nodes separately. Keep
   the external Logitech camera outside the P16 acceptance claim.
2. Test a bounded live RGB capture to a temporary buffer, verify nonblank
   changing frames, resolution, frame rate and timestamps, and close the
   device cleanly. Test IR separately; device enumeration alone does not imply
   useful IR imaging or face-authentication support. Verify camera privacy
   controls and that another application receives the expected busy/permission
   behavior while capture is active.
   A first probe can use `v4l2-ctl -d /dev/video0 --list-formats-ext` followed
   by `ffmpeg -f v4l2 -i /dev/video0 -frames:v 30 -f null -`, selecting a
   format/rate from that node's reported capabilities. The probe must show
   captured frames and sensible timing, not just an open file descriptor.
3. Verify normal user access through V4L2 and the active PipeWire/portal path
   where the application uses it. Confirm a browser/WebRTC call preview and an
   OBS or equivalent recording with correct A/V sync. Repeat after suspend and
   application restart. No permanent recording is needed for a smoke test.

### Models with ACPI MIPI/CSI sensors

This is a separate implementation project on an affected laptop, not a P16
package flag. Before coding, collect that model's DMI/BIOS, ACPI tables and
device resources, sensor/EEPROM identity, clocks, regulators, reset/privacy
signals, IOMMU/DMA constraints and available signed firmware. Preserve any
unknown register semantics as unknown. Check current MediaTek/NVIDIA and
linux-media work for the exact controller revision and ACPI binding.

1. Implement or adapt sensor, CSI receiver/SENINF, camera controller and ISP
   drivers under the Linux media subsystem. Match ACPI IDs and validate
   resources/firmware ABI; use V4L2 subdevices, Media Controller entities and
   the relevant buffer/request APIs. Represent sensor → CSI → ISP → capture
   links and controls in the media graph. Do not use a private raw mailbox
   ioctl, arbitrary register pokes, Windows binaries or a fake USB camera.
2. Cover probe deferral, clock/power/reset order, privacy state, IOMMU mappings,
   DMA buffer lifetime, stream start/stop, format negotiation, error unwind,
   runtime PM, suspend and removal with offline fault tests and kernel
   diagnostics. Build both module and intended in-tree forms against the target
   kernel. Discuss bindings and driver ownership with linux-media maintainers.
3. Add a model-specific libcamera pipeline/IPA only if generic V4L2 discovery
   cannot expose correct sensor controls and ISP processing. Use documented
   [Media Controller/V4L2 interfaces](https://docs.kernel.org/userspace-api/media/mediactl/media-controller-intro.html)
   and [libcamera pipeline design](https://docs.libcamera.org/master/guides/pipeline-handler.html).
   Package firmware and calibration data only with established provenance and
   redistribution rights; never borrow another laptop's sensor tuning.
4. On that exact machine, prove a real sensor image at the supported resolution
   and rate, exposure/white-balance control, color and IR behavior where
   present, privacy switching, repeated start/stop, hot application restart,
   fresh boot and physical resume. Then prove browser/WebRTC and a desktop
   capture application consume the libcamera/V4L2/PipeWire path. A media graph
   with no usable frames is an intermediate result, not completion.

## Delivery order and completion record

1. Land the codec capability inventory and repeatable test corpus. Package
   NVENC-capable ARM64 FFmpeg; qualify NVDEC and NVENC independently, then
   playback, recording, browser, concurrency and PM.
2. Qualify the existing P16 RGB and IR cameras with real applications. File
   separate model-specific work for MIPI/CSI laptops once one is available for
   physical bring-up; do not mark the P16 blocked on hardware it does not have.
3. Investigate each requested video effect's Linux artifact. Integrate an
   available Linux backend with real application usage, or keep the exact
   NVIDIA feature open with a named vendor/API blocker and an explicitly named
   alternative.
4. Submit durable kernel fixes to the appropriate subsystem and reproducible
   user packages to Omarchy. Preserve source attribution and avoid private
   machine paths or firmware dumps in public packages. Record the tested
   package commit, installed version and normal-boot application result.

A completion entry for **each** feature must link: source/package commit and
hashes; exact machine/firmware/kernel/driver; advertised and queried
capability; passing and failing test cases; user application and selected
backend; output or capture evidence; hardware-use proof; boot/resume result;
remaining limits. The label **supported and used** is reserved for features
that pass all applicable gates on the named hardware. Broader N1X support
requires the same record on each materially different camera/firmware design.
