# Missing N1X media support: implementation and use plan

This is the qualification path for video codecs, GPU video effects, and camera
capture on Linux/Omarchy. The goal is **a working consumer application using the
intended hardware path**, not merely a bound driver, an advertised capability,
or a successful synthetic API call. Each result belongs to an exact machine,
firmware, kernel, NVIDIA driver, userspace build, and application version.

## Baseline and scope (18 November 2026)

The reference machine is the ASUS ProArt P16 H7607BA, 20-core RTX Spark N1X,
running `7.2.8-36-rtx-spark-npu` and NVIDIA `615.78.08`. NVIDIA's [N1X codec
matrix](https://developer.nvidia.com/video-encode-decode-support-matrix) lists
one ninth-generation NVENC, one sixth-generation NVDEC, up to 12 concurrent
encode sessions, H.264/HEVC/AV1 encoding, and a much broader decode/profile
matrix. That is a hardware capability list, not Linux qualification.

On this P16, `/dev/video0`–`3` are the internal ASUS RGB/IR USB cameras;
`/dev/video4`–`5` belong to an attached Logitech StreamCam. None is an NVENC
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
| NVDEC | H.264, HEVC and AV1 8-bit plus HEVC/AV1 10-bit, VP9 8/10/12-bit, VP8, MPEG-2 and MJPEG samples pass through VA-API and direct CUVID; the installed mpv playback command uses H.264 hardware decode | Advertised format/profile cases tested where supported; browser and desktop playback, plus boot/resume, demonstrably use hardware decode |
| NVENC | Isolated ARM64 FFmpeg package built; NVENC session fails with error 21 on driver 615.78.08. Vulkan Video H.264/HEVC/AV1 8-bit plus HEVC/AV1 10-bit encoding works through a different API, including a 60-frame real RGB camera recording in FFmpeg | A packaged Linux NVENC encoder path, verified H.264/HEVC/AV1 outputs, and an actual recording or stream using NVENC |
| GPU video effects | Installed mpv/libplacebo Vulkan scaling and interpolation exercised in playback; connected displays run in sRGB with no active HDR metadata; proprietary Linux ARM64 SDK path unverified | Each selected effect runs through a supported Linux implementation and is consumed by a real application; unsupported vendor SDK features remain explicitly open |
| P16 USB cameras | RGB and IR live capture passes; RGB preview in mpv and Chromium WebRTC, and six-second OBS recording pass | Privacy, graphical browser permission, PipeWire portal and resume tested independently |
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
The OBS camera recording used the existing V4L2 interface and the x264
software encoder; it proves application camera use, not hardware encode.
A separate FFmpeg recording used the live RGB camera with NVIDIA Vulkan Video
H.264 hardware encode and independently verified 60 frames. OBS's advanced
FFmpeg output failed to open `h264_vulkan` with `Invalid argument`; its hardware
recording gate remains open. Neither Vulkan result proves NVENC API use.
The [`p16-media-tools` package](platform/video/tools/README.md) provides explicit
mpv hardware playback and P16 RGB/Vulkan recording commands without replacing
system codecs. Version 0.1.0-1 is installed on the reference P16: the installed
mpv command played through VA-API and Vulkan/libplacebo to EOF, and the
installed recording command produced a 60-frame H.264 file from the live RGB
camera. The temporary footage was deleted after independent probing. This
qualifies those specific Linux workflows on this machine; it does not close
NVENC, OBS hardware recording, HDR or power-management gates.
The [media resume preflight](docs/evidence/n1x-media-resume-20261118/README.md)
stopped before sleep: ACPI TAD RTC1 returned `Input/output error` and EFI RTC0
returned `Invalid argument` when asked to arm a wake alarm. NVIDIA kernel
suspend notifiers are active and the verified VT handoff must be preserved.
No after-resume media result is claimed.

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

Optical flow and JPEG acceleration may be investigated separately by querying
the exact N1X driver/API capabilities. Do not infer dedicated OFA/NVJPEG blocks
from another NVIDIA SoC or from the presence of CUDA libraries; add a test row
only after a device-specific capability and runtime path are established.

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
