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

### Follow-up on 620.70.06

The NVIDIA archive includes `libnvcuextend.so.620.70.06`, which the installed
Arch package omits. The CUDA session probe tried that library and loaded it
successfully when it was supplied from a private `LD_LIBRARY_PATH`. The
matched vendor file left the session result at 21. Tracefs rejected attaching
a kernel probe to the NVIDIA control function, so the trace establishes the
userspace/RM boundary and leaves host RM versus GPU firmware attribution open.

### NVENC session handle correction on 620.70.06

A second RM trace recorded the client and object handles. Both direct probes
allocated a subdevice of class `NV20_SUBDEVICE_0` (`0x2080`) and completed
`0x20808165` on that object. The next call, `0x20808163`, used the same client
with object handle `0`. That call returned `NV_ERR_OBJECT_NOT_FOUND`.
Userspace debugging located both calls in `libnvcuvid` and showed the second
call reading the zero handle from its session state. The open RM first looks
up the requested object in the client's resource map. [RM dispatch](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/620.70.06/src/nvidia/src/libraries/resserv/src/rs_server.c#L1589),
[resource lookup](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/620.70.06/src/nvidia/src/libraries/resserv/src/rs_client.c#L383).

The installed [Arch package](../../platform/nvidia/620/nvenc/PKGBUILD)
provides `p16-nvenc-run`. Its process-local shim supplies the allocated
subdevice handle when the same thread, client, and file descriptor have
just queried that subdevice and then pass handle `0` for the failing
control. The driver still processes the original command and returns its
status. The launcher checks the loaded kernel driver version and the exact
vendor encoder and decoder libraries before loading the shim. The vendor
libraries and kernel modules on disk retain their original contents.

With `p16-nvenc-run`, the direct CUDA and EGL/OpenGL probes both opened and
destroyed an NVENC session successfully. The native driver returned zero
from the corrected control. Installed `ffmpeg-n1x` encoded 90 frames of
1280×720 motion using each explicit NVENC encoder. System FFmpeg identified
the requested codec and decoded every frame with `-xerror`. A second FFmpeg
process opened all three encoders together and wrote 120 frames per stream.
All three streams decoded cleanly. NVML's active-session counter reported
zero during the run. In a separate traced run, each of the three NVENC
encoders allocated NVIDIA's `NVD1B7_VIDEO_ENCODER` class (`0xd1b7`) with
status zero after the corrected control call. The sequential media corpus
passed all 35 cases, including all three NVENC encodes. The earlier run
that overlapped the corpus and the three-stream encode logged one NVRM
`NV_ERR_NO_MEMORY` warning. The warning was absent from the sequential
corpus and the traced encode checks.

```sh
p16-nvenc-run ffmpeg-n1x -f lavfi -i testsrc2=size=1280x720:rate=30 \
  -frames:v 90 -c:v h264_nvenc /tmp/p16-nvenc-h264.mkv
```

The same invocation accepts `hevc_nvenc` and `av1_nvenc`. This installation
and all tests used the running `@nvidia620` root and driver 620.70.06. The
earlier 610 comparison entry was removed and the original Limine menu
restored.

### DRM flip timeout on the internal panel

The journal shows two timeouts on head 0 before the targeted trace. Each
timeout preceded the empty-queue warning in `__nv_drm_handle_flip_event`.
The first occurred during desktop startup and the second near an idle
transition. In the matched 620.70.06 source the timeout path drains the
flip queue. A later hardware event then reaches a queue with no flip.

Two internal-panel DPMS off/on cycles ran under a timing trace on the same
boot. The first off transition reproduced the timeout and warning. The
blocking Hyprland atomic commit took 3,388 ms. The content protection work
item and the topology handler on the NVIDIA events thread each took 3,010
ms and returned as the commit finished. The second off transition took
364 ms and produced no timeout. The trace matches the lock cycle where the
commit holds `connection_mutex`, the worker holds `mode_config.mutex`
while waiting for `connection_mutex`, and the NVIDIA events thread needs
`mode_config.mutex` before it can deliver the flip. NVIDIA tracks the
symptom as 7126445. [NVIDIA issue](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1553),
[related lock-cycle trace](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1361).

The [620 patch](../../platform/nvidia/620/nvidia-drm-content-protection-flip-deadlock.patch)
makes the content protection worker try `connection_mutex` without
waiting. A busy lock causes it to drop `mode_config.mutex` and defer the
pending work by 10 ms while events remain enabled. The original hardware
flip acknowledgement, timeout path and DRM completion accounting remain
intact. The extracted worker passed contention, retry and teardown checks
under ASan and UBSan. Matching kernel38 modules built, and `pahole` parsed
the new `nvidia_drm` split BTF against kernel38 `vmlinux`.

| Artifact | Identity |
| --- | --- |
| Patched `nvidia-drm.ko` | `srcversion B0610EE874678B18EA30A07`, SHA-256 `2a9b1b7c2faeb2dfce9e7e8ca09cdaae85922fa577535735d97ed3721ea22e7c` |
| DKMS patch package `620.70.06-2` | SHA-256 `4d9134ed342396d9e18949a71d09cc4382242a7b3870343cd9ee06bfc147040c` |
| Loaded `nvidia_drm` | `srcversion 9D0450148A72C2F9BA9F89A` |

The patched module passed two native DPMS cycles in the combined candidate
boot. See the [native results](#native-dpms-and-s2idle-results).

### Physical s2idle preflight

On the loaded 620 modules before a physical test, the internal display,
direct CUDA and EGL NVENC sessions, independently decoded H.264/HEVC/AV1
samples, and RGB/IR capture all passed. The speaker and microphone kernel
PCM positions advanced and the three DSPs reported ASoC ready. The cuDLA
positive and negative ReLU inputs each returned 3,136 bytes equal to their
independent references. The installed VT handoff is a dependency of
`systemd-suspend.service` with kernel suspend notifiers active.

The boot already lost Lockdep validation after a CUDA-thread lock warning
at 11:13:54 involving `fs_reclaim` and MMU-notifier invalidation. A physical
test in this boot can establish functional resume. Continuous Lockdep
qualification requires a clean boot with matching artifacts. EFI RTC has
no `wakealarm` and ACPI TAD returned `EIO` when setting an alarm. Physical
sleep requires an attended power-button wake.

### Physical s2idle attempt and recovery

One attended `systemctl suspend` on kernel38 and NVIDIA 620.70.06 at
11:45:50 CET aborted in PM PREPARE. The installed VT handoff and user slice
freeze completed. The kernel logged `PM: suspend entry (s2idle)`,
`NVRM: PM suspend notifier failed: 0x56` and `PM: suspend exit` within
549 ms. The success counter stayed at 0, failures rose from 0 to 1, and
`last_failed_errno` was `-1` (`EPERM`). Hardware sleep stayed at zero and
systemd thawed the user slice and restored tty1 on the same boot.

The NVIDIA 620.70.06 HAL selects the unsupported power-management handler
for GB20B. `RmInitPowerManagement()` transfers that result into
`nv->is_pm_unsupported`. `nv_suspend_devices()` returns
`NV_ERR_NOT_SUPPORTED` (`0x56`) at its device check, before suspend work
in modesetting, UVM and allocations. The PCI PM path also checks that flag.
This P16 has GB20B PCI ID `10de:2e03` and ASUS subsystem `1043:1484`.
A report on a P16 with the `2e06` variant and 620.73.04 reproduced the same
refusal and completed four physical cycles after admitting GB20B to the
existing suspend sequence.
[620 HAL table](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/620.70.06/src/nvidia/generated/g_gpu_nvoc.c#L956),
[RM flag assignment](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/620.70.06/src/nvidia/arch/nvalloc/unix/src/dynamic-power.c#L3201),
[NVIDIA issue #1577](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1577).

| Check | Result in the same boot |
| --- | --- |
| Display and GPU | Internal panel active, NVIDIA EGL/OpenGL renderer available |
| NVENC via `p16-nvenc-run` | CUDA and EGL sessions opened. Each of H.264, HEVC and AV1 encoded 10 frames that decoded independently. |
| V4L2 cameras | RGB and IR each captured all 30 requested frames |
| Internal audio after abort | HiFi1 ASoC readiness dropped to 0, IPC and PCM startup returned `-110`, and PipeWire lost the speaker and microphone nodes. Every DSP recorded zero sleep cycles. |
| Internal audio after checked DSP/AFE reload | Both PipeWire nodes returned, all three DSPs reported ASoC ready, and hardware PCM pointers advanced for simultaneous playback and capture. Capture returned 384,000 bytes with nonzero samples. |
| cuDLA | Two ReLU cases after recovery each returned 3,136 bytes equal to an independent reference |

The repository's `scripts/qualify-dsp-reload.py --reload` performed the
audio recovery after checking the live versions and shutdown support.
An independent FFmpeg capture through PipeWire's PulseAudio server
returned 96,000 stereo microphone frames at 48 kHz and exited successfully.
The camera and encoder checks also passed when repeated after recovery.
The cause of the DSP IPC failure during abort recovery remains open.
Physical sleep, device resume, and clean Lockdep qualification remain
pending. The DRM module loaded during the attempt was
`9D0450148A72C2F9BA9F89A`.

### GB20B s2idle candidate

The [620 PM patch](../../platform/nvidia/620/nvidia-p16-gb20b-s2idle.patch)
adds a load-time opt-in for the measured P16 DMI and PCI IDs. It requires
kernel suspend notifiers and checks the selected s2idle mode in PREPARE,
then the actual target state during PCI device PM. Both guards use the same
predicate. The patch keeps NVIDIA's capability flag, modeset and UVM
operations, allocation preservation and error propagation in place.
The installed systemd sleep policy selects `mem` with `s2idle`.

The signed 620.70.06 distribution source with all five DKMS patches built
five ARM64 modules against `7.2.8-38-rtx-spark-npu`. Their split BTF parsed
against the matching `vmlinux`. The same PM predicate passed 19 focused
checks under ASan and UBSan. The checks covered PREPARE, the PCI callback,
opt-in, both device identity checks, legacy PM, S3 and hibernation.
Reapplying the patch files from the built DKMS package with fuzz zero
reproduced the compiled PM source.

| Artifact | Identity |
| --- | --- |
| Candidate `nvidia.ko` | `srcversion 3D15902633EDCE9CFBEB1C9`, SHA-256 `aa684d0aea475a99b5d9b4340fa73628615f7e50db72822fc34f2577aed74c32` |
| Candidate `nvidia-drm.ko` | `srcversion B0610EE874678B18EA30A07` |
| DKMS patch package `620.70.06-3` | SHA-256 `f56c9425135429b28b154c71be7da53a126d44f4eee91fb18efd931696f497e0` |

Release 3 was built offline. For combined native qualification, boot the
matched candidate with `nvidia.p16_s2idle=1` and confirm both loaded
srcversions, the module option and active Lockdep. Exercise internal-panel
DPMS, then run one attended s2idle cycle. Require one additional suspend
success, zero new failures, return to the same desktop, and repeat the GPU,
NVENC, RGB/IR, audio PCM and cuDLA tests. Check the kernel journal for flip
timeouts, NVIDIA faults, audio IPC timeouts and Lockdep warnings. Collect
the failure state before further sleep requests if the cycle fails.

#### Single-reboot staging

The combined candidate was staged on 27 November in a writable clone of
the working `@nvidia620` root. Select **P16 NVIDIA 620 DRM + Suspend Test**
in the normal Limine menu. It starts `@nvidia620-r3` (Btrfs ID 270) with
`nvidia.p16_s2idle=1`. The original **P16 NVIDIA 620 Test** entry still
selects the original 620 root. During staging, **Omarchy/linux-p16-platform-36**
remained the menu default and the **Omarchy-P16-Recovery** image also
passed validation. The firmware boot order stayed `0002,0001,2001,2002,2003`
with no BootNext, and the running boot ID and loaded module versions
stayed the same during staging.

| Staged artifact | Identity |
| --- | --- |
| UKI `/boot/EFI/Linux/p16_nvidia620_kernel38_r3.efi` | SHA-256 `271fc002d893c400fcc9a9c546b4117fc5c43325a57aa2a412e86e2c4ae7f42b` |
| `linux-p16-platform-38-drivers-nvidia620 7.2.8-38.1` | SHA-256 `4162d741c400f015d3aa413a794123b9094787c104575b71d2ac079315a77cfe` |
| Limine backup | `/boot/limine.conf.before-nvidia620-r3-20261127T120529Z` |

The clone's fstab points to its own root subvolume. Its package transaction
updated the DKMS patch recipe and the matching module bundle.
Eight platform modules were byte-identical to
the original bundle. Both candidate packages reported zero altered
files. `mkinitcpio --nopost` built the image with the legacy ACPI
profile and the existing audio boot arguments. The platform verifier
checked BTF for 8,504 installed and 430 embedded modules. The four
embedded NVIDIA files matched the installed files byte for byte, and
Limine's full menu passed its image and BLAKE2b checks. The original
EFI executables retained their hashes. The build emitted a missing
optional Renesas xHCI firmware warning and skipped the microcode hook
on ARM64.

Local staging log, bundle recipe and test helpers live under
`build/nvidia620-r3-single-boot/` in this checkout. The test fixtures
are on the shared home subvolume and survive reboot. Run
`qualify/qualify pre` in the logged-in desktop. It checks the loaded
DRM and PM module identities and the opt-in, then runs two internal
panel DPMS cycles, GPU and NVENC checks, RGB/IR camera capture and
internal audio. After that passes and an attended wake is ready, run
`qualify/qualify suspend` with graphical Polkit. It checks cuDLA before
sleep, records Lockdep and PM counters, sends one suspend request and
repeats all device and cuDLA tests after wake. Logs are grouped by boot
ID. The media and audio checks passed a dry run on the original boot.

#### Native DPMS and s2idle results

The first start from **P16 NVIDIA 620 DRM + Suspend Test** reached the
Hyprland desktop on kernel `7.2.8-38-rtx-spark-npu` and `@nvidia620-r3`.
The live NVIDIA and DRM srcversions were `3D15902633EDCE9CFBEB1C9` and
`B0610EE874678B18EA30A07`. The candidate reported `p16_s2idle=Y`
with NVIDIA suspend notifiers and allocation preservation enabled.
On 28 November, two DPMS off/on cycles on `eDP-1` completed without a
DRM flip timeout or empty-queue warning. The panel ran at 3840×2400 at
120 Hz before suspend and after resume.

One attended s2idle request completed on boot
`c0c9507c-2d78-4f67-802b-770af443bd26`. The kernel success counter rose
from 0 to 1, the failure counter stayed at 0, and the desktop returned
on tty1 with the same boot ID. The systemd sleep operation took 47.0 s
including device transitions. The hardware residency counter
`last_hw_sleep` stayed at zero, so the test establishes functional
s2idle and resume. Deep platform residency remains unmeasured.
The journal recorded VT handoff, user slice freeze and thaw, NPU
shutdown and reinitialization, and successful reinitialization of all
three audio DSPs. All three DSPs reported one sleep cycle with zero
errors and matching pre/post configuration. Lockdep reported
`debug_locks=1` before and after the test. The test window contained no
NVIDIA PM refusal or Xid, DRM flip timeout, audio IPC/ASoC error, or
Lockdep warning.

| Check | Before and after s2idle |
| --- | --- |
| GPU and NVENC | NVIDIA EGL renderer, direct CUDA and EGL encoding sessions. H.264, HEVC and AV1 each produced 10 independently decoded frames via `p16-nvenc-run`. |
| Cameras | RGB and IR each delivered all 30 requested V4L2 frames. |
| Audio | Internal speaker and microphone hardware PCM pointers advanced simultaneously. Each capture returned 384,000 bytes with nonzero samples. All three DSPs reported ASoC ready. |
| NPU | Two numerical ReLU cases each returned 3,136 bytes bit-equal to the independent references, with inputs unchanged. |

This was one physical cycle with device workloads run before and after.
Repeated sleep, allocation retention across sleep and external display
through the hub remain outside this result.

#### Default boot

After qualification on 28 November, Limine's persistent `default_entry`
was set to **P16 NVIDIA 620 DRM + Suspend Test**. The menu selects the
qualified kernel38/620.70.06 UKI and its `@nvidia620-r3` root. The two
patched NVIDIA modules and `nvidia.p16_s2idle=1` are in that boot.
The UKI matched its recorded SHA-256 and the complete menu passed its
image and BLAKE2b checks before publication. The updated menu was read
back from the EFI partition.

**Omarchy/linux-p16-platform-36**, **P16 NVIDIA 620 Test** (the original
620 root) and **Omarchy-P16-Recovery** remain available in Limine. The
firmware boot order is `0002,0001,2001,2002,2003` with no BootNext.
The prior menu was saved at
`/boot/limine.conf.before-default-nvidia620-r3-20261128T085627Z`.
This change used the existing start image and required no reboot.
