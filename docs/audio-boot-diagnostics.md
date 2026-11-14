# Audio test boot failure, repair and verification

**Native kernel31 boot succeeded on 13 November 2026 after the split-BTF repair.**
The first checked DSP/AFE unload/reload and device-only PM tests also succeeded
later that morning. Two reload cycles passed PCM and numerical NPU checks;
real s2idle and clean Lockdep qualification remain pending. Kernel23 is still
the preserved default and recovery baseline.

On 12 November, selecting `RTX-Spark-Audio-Test` produced an immediate black
screen that remained for ten minutes. The failed attempt did not leave a
persistent kernel31 journal entry. The investigation below separates that
history, the console-output gap and the confirmed module-coherence defect.

The failed ARM64 `Image` has SHA-256
`ab39c02c03334e5cd665758502cde89f04667572112e34494f7bba3bacc69fd1`.
The previously working kernel31 image has SHA-256
`786ba498bd872a33b51b2eccefadb28888f007183bb171866079e90551b1c7b8`.
Their ARM64/PE headers match. Comparing the saved UKIs also found identical EFI
stub sections, initramfs and ACPI payload; the kernel changed, along with a
trailing command-line space. Those initial comparisons did not detect the
split-BTF mismatch described below.

Both kernel images passed isolated direct and EFI/KVM startup with KASLR and a
minimal userspace test covering vDSO time reads, signal return and fork. EFI
framebuffer early-console setup also worked in the virtual platform. These
checks do not exercise N1X ACPI, SSPM, NVIDIA graphics or DSP hardware. A later
abrupt restart of the kernel23 host remains unexplained; further VM testing on
that host was initially stopped. On the user's request, a later serialized batch
ran 18 more KVM boots: six direct and three EFI/framebuffer boots for each image,
with one vCPU and 2 GiB RAM per guest. All 18 passed while other workloads stayed
running. No host freeze was reproduced during the batch or more than five
minutes after the final guest exited. A separate Qwen workload then coincided
with ACPI thermal readings reaching 95.2 C while no VM was running; this does
not establish the cause of the earlier freeze. Do not treat the virtual smoke
tests as physical qualification of the N1X startup path.

A logging-only replacement was first installed as
`RTX-Spark-Audio-Diagnostics`, retaining the failed kernel and initramfs while
preserving the working kernel23 default and recovery entries.

## Scoped SSPM correction

The old/new object comparison narrowed executable-code changes to SSPM and
PowerWrap. In particular, the failed candidate replaced the normal transport's
bounded late-ACK drain with a permanent rejection of every later SET after one
submitted timeout. Since platform boot and power management share that
transport, this could disable subsequent device power transitions. No log from
the failed native boot establishes that such a timeout actually occurred; the
previous successful kernel31 journal contains no recorded SSPM timeout.

The corrected patch restores the original normal transport and adds
`sspm_ci_set_checked()` only for the destructive DSP-shutdown helper. Every
submitted timeout still permanently disqualifies checked shutdown commands.
Rebinding, a late ACK or successful normal recovery cannot clear that history
or authorize DMA reclamation. All six existing PowerWrap dispatch callers,
plus the direct probe and request paths, retain normal transport semantics.

The actual old/new normal sender functions produced identical results across
73 simulated transactions, including timeout, late-ACK drain and rebind.
Separate sanitizer tests cover checked refusal, normal recovery after a
checked timeout, native D3/abandon wire payloads and partial-stage handling.
These tests establish the intended software boundary, not physical bootability.
The corrected kernel is rebuilt from the previously working kernel31 tree,
with the same configuration and build identity, applying only the scoped
SSPM/PowerWrap patch. Hardware startup and full audio reload remain pending.

The scoped candidate was installed in `RTX-Spark-Audio-Diagnostics`, with
matching kernel31 `vmlinuz`, System.map, debug-stripped vmlinux and symbol
versions. Its kernel SHA-256 is
`5b3282f08458c3bfc59e89218f6fe78f0ac3e830a81ea3ed859820db5de9fb2a`;
the UKI SHA-256 is
`e45bea823803eabd2f687a7597c8fe3cfb2f58b69c67fcd316e65dff6357ea06`.
Only the kernel payload changed from the logging-only UKI: initramfs, ACPI,
EFI stub, command line and section load addresses were preserved. The Limine
BLAKE2b pin was updated and verified. Kernel23 remains the default; recovery,
other entries, installed modules, live drivers and power profile are unchanged.
The previous test bundle is backed up under
`/var/lib/p16-platform/audio31-scoped-shutdown-20261112`.

All 162 repository tests and the offline driver suite passed. All 8,509
installed modules' 442,068 symbol imports match the new kernel and installed
module exports; existing kernel export CRCs are unchanged. Direct KVM startup
passed. The additional EFI run was stopped by the host-temperature guard at
90 C before reaching the userspace marker; it is not a passing EFI result or a
confirmed kernel failure. The host remained on the same boot. No claim of
successful native boot or completed DSP reload follows from these checks.

## EFI-to-dummy-console output gap

A second native attempt with the scoped kernel did not reach a usable boot.
The photograph taken on 12 November at 18:00 shows these final lines:

```text
Console: colour dummy device 80x25
printk: legacy console [tty0] enabled
printk: legacy bootconsole [efifb0] disabled
```

The last line is at approximately 0.195 seconds. It marks the loss of visible
output when the dummy VT console replaces EFI earlycon. It does not locate the
actual hang. The timer firmware warning visible above it also occurs in the
previous successful kernel31 journal. No failed-boot journal or pstore record
was recovered. The SSPM correction has not established successful native boot.

A bounded EFI/KVM comparison used the same scoped kernel, one vCPU, 2 GiB RAM,
`console=tty0` and the same SimpleDRM blacklist. Both guests reached userspace,
reported independently through the virtual UART. With the old diagnostic
arguments, the framebuffer remained at the bootconsole-disabled message.
With `keep_bootcon` and `loglevel=8`, a later userspace marker and initcall
tracing were visible in a framebuffer screenshot. Maximum host thermal reading
was 61.2 C. This reproduces the observation gap without claiming to reproduce
the hardware boot failure.

The revised diagnostic UKI was installed as `RTX-Spark-Audio-Diagnostics`. It
retained EFI earlycon past dummy-console registration and prints DEBUG-level
initcall entry/return messages. Kernel, initramfs, ACPI,
module set and boot policy remain unchanged. Its SHA-256 is
`5aa846f334bf0a9349591535ab383ff72f1cdd41aab44408ee79a774f05aa07b`.
The previous image and menu are backed up under
`/var/lib/p16-platform/audio31-console-handoff-20261112`. This is temporary
console instrumentation; retained EFI output may overlap a later graphics
console. Kernel23 remains the default. These arguments exposed the later
split-BTF module failure described below.

## Confirmed split-BTF module mismatch

The 13 November diagnostic photograph reaches approximately 95 seconds and
shows repeated `BPF: Invalid name` and
`failed to validate module [...] BTF: -22`, including WMI, SPI, USB and crypto
modules. The kernel's relink changed its base BTF, while the earlier deployment
retained native modules and initramfs copies built against the old base.
Kernel release and symbol-CRC checks passed despite that incompatible split
BTF. This is a confirmed package-coherence defect and blocks module loading;
the earlier SSPM hypothesis did not establish the cause of the failed boot.

Offline parsing reproduces the fault: the old USB module's BTF parses against
the original vmlinux and returns `EINVAL` against the relinked vmlinux. Native
modules generally refer directly to base type IDs. External modules carrying
`.BTF.base` can relocate those references, as described in the
[Linux BTF documentation](https://docs.kernel.org/bpf/btf.html#btf-base-section).
The repair regenerates the complete native module set against the current
kernel, retains BTF validation, checks external-module relocation and rebuilds
the diagnostic initramfs from the matching installed modules.

A single EFI/KVM guest using the corrected kernel rejects the deliberately
supplied old WMI module with the expected BTF error, then loads 28 corrected
modules successfully. They cover WMI, SPI, USB, MMC helpers, crypto, I2C,
SPI-HID and the NPU/DSP/AFE/ASoC modules plus dependencies. The guest powers off
normally. These are actual kernel module-loader results; native N1X devices,
firmware execution and audio streaming are outside that VM qualification.

The read-only verifier `scripts/verify-module-btf.py` uses libbpf to parse split
BTF and relocate embedded `.BTF.base` descriptions. It also checks that the
vmlinux BTF bytes occur in the selected raw kernel Image. Candidate preparation
checks native and external modules; the managed update check checks both
installed modules and copies extracted from the UKI. The helper is packaged
with `p16-platform-policy` 1.3.1 and depends on libbpf. It never loads a module.
Seven regression tests cover changed base type IDs, distilled-base relocation,
matching kernel images, compressed modules, missing BTF and malformed ELF.

The BTF repair is installed in `RTX-Spark-Audio-Diagnostics`: 8,490 signed native
modules were replaced, all 8,509 modules passed BTF checks, and all 442,069
symbol imports matched. All 430 embedded initramfs modules passed the BTF
check and matched their installed files byte for byte. The new UKI SHA-256 is
`ba7c8e1a74e77fe07c86ca1b3aa104a20773e473fa7cf144a9e7996c68c27d72`.
The kernel Image remains
`5b3282f08458c3bfc59e89218f6fe78f0ac3e830a81ea3ed859820db5de9fb2a`.
Its base BTF SHA-256 is
`883dd59a9f0200b4e27e488f2e48a8cc77ab0b7585f5a4441689cc7cef4c0523`.
The existing early ACPI payload and kernel arguments were preserved. Limine
hash verification passed. The previous module tree, changed headers, update
checker and boot files are backed up under
`/var/lib/p16-platform/audio31-btf-repair-20261113`. Kernel23 remains the default;
recovery, other boot images, live modules and power profile were unchanged.
The subsequent native boot is recorded below; DSP reload still needs physical
qualification.

## Successful native boot and PCM checks

On 13 November at approximately 08:35 local time, the repaired diagnostic entry
booted `7.2.8-31-rtx-spark-npu` into the Hyprland desktop. The runtime
`/sys/kernel/btf/vmlinux` SHA-256 matches the installed bundle's base BTF hash
above. The boot journal contains zero module-BTF validation failures. NVIDIA
615.78.08 responds, the NPU firmware initializes and exposes `/dev/accel/accel0`,
and all three DSPs report `ready=1`, `error=0` and `asoc_ready=1`. DSP 0.1.25 and
AFE 0.1.27 are loaded; the internal SoundWire ALSA card is present. There are no
failed system or user systemd units at verification time.

The bounded audio validator then passed all six three-second PCM tests:
playback, capture and duplex in S16_LE and S24_LE, with matching capture byte
counts, nonzero recordings and advancing firmware counters. No services were
stopped and no drivers were unloaded. This verifies the native boot and the
tested PCM transport; NPU numerical execution, DSP reload, physical endpoints
and suspend were not exercised.

The debug kernel reported `MAX_LOCKDEP_CHAIN_HLOCKS too low` in a Btrfs
transaction before PCM testing and disabled lockdep. This is a debug capacity
failure, so a clean lockdep qualification remains outstanding. The boot entry,
default selection and power profile were left unchanged during verification.

## Fixed-IRQ lifetime and first native reload

Device-only PM subsequently passed twelve three-second PCM rounds: playback,
capture and duplex in both formats before and after DSP D3/D0 and firmware
REINIT. SoundWire card registration finishes asynchronously after PM returns;
the validator now waits for both ALSA directions before opening PCM devices.
Eight pinned cuDLA outputs across ReLU, convolution and convolution-plus-ReLU
graphs matched independently generated references, including changing-input
task reuse. These tests do not establish real s2idle or physical endpoint quality.

The first shutdown exposed a separate MediaTek common-driver lifetime bug.
`mtk_afe_fe_shutdown()` cleared `memif->substream` only for dynamically allocated
IRQs. N1X uses fixed IRQs; the reservation survives close but the borrowed ALSA
pointer must not. The checked SRAM owner correctly refused retirement with
`EBUSY`, and read-only tracing showed two closed borrowers still referenced by
their memifs. `p16-afe-const-irq-shutdown.patch` clears both kinds of borrower
while retaining the fixed IRQ reservation. The sanitizer regression reproduces
the old failure and checks both allocation modes.

A tightly scoped [temporary livepatch](../platform/dsp/livepatch/README.md)
was tested under KVM, checked against six exact private BTF layouts, then applied
to kernel31. It retired exactly two stale pointers. The maintenance helper
continued in the same boot, completed native DSP shutdown and SRAM/operating-DMA
retirement, unloaded/reloaded DSP and AFE, and started all three firmware cores
with `ready=1 error=0`. Six PCM rounds and eight exact cuDLA outputs passed after
this first complete reload. The NPU provider stayed loaded throughout.

One aborted device-PM request also exposed Python buffered sysfs replay:
`TextIOWrapper` could submit again during close after the first write returned
`EBUSY`. The maintenance helper and validator now use exactly one unbuffered
`os.write()` per command and never retry an ambiguous hardware operation.

The next separate kernel candidate raises `LOCKDEP_CHAINS_BITS` from 16 to 18,
increasing chain and held-lock capacity fourfold. Current-boot functional tests
cannot restore the already-disabled validator; clean Lockdep qualification
requires that complete matching kernel/module bundle to boot successfully.

The second native reload also passed all six PCM rounds and eight exact cuDLA
outputs. A subsequent device-only PM cycle using the unbuffered command path
passed another six PCM rounds and eight exact cuDLA outputs; the SoundWire card
was ready within 0.019 seconds of PM returning. These remain device-only tests.

Journal review found a separate NVIDIA 615.78.08 display cleanup defect:
`nv_drm_reset_input_colorspace()` returned `-EDEADLK` without the DRM backoff
protocol, triggering `drm_modeset_drop_locks()` during logind's master drop.
The [version-scoped NVIDIA patch](../platform/nvidia/README.md) corrects the
transaction and is included in the next private module candidate. It has not
replaced the running desktop driver. An earlier DMA-debug warning arose in the
USB webcam's `dma_alloc_noncontiguous()`/`uvcvideo` allocation path, separately
from DSP retirement; it is not a clean global DMA-debug qualification.

The attempted real-sleep qualification stopped **before suspend** because the
ACPI TAD RTC rejected its wake alarm with `EIO`. Both AC/DC timer readbacks
remained zero. The captured AML implements `_STV` through the secure FF-A RTC
service (command 6), while `_GCP` advertises wake support; the rejection alone
does not establish which secure-side condition failed. Real s2idle needs a
coordinated manual wake or a verified working alarm. It is not reported passed.

## Kernel32 offline qualification

`7.2.8-32-rtx-spark-npu` was subsequently built with KASAN,
`LOCKDEP_CHAINS_BITS=18`, the permanent fixed-IRQ close patch and matching
NVIDIA 615.78.08 modules containing the colorspace deadlock backoff fix.
Its separately named kernel and headers packages are `linux-p16-platform-32`
and `linux-p16-platform-32-headers`; they do not replace the kernel31 packages.
The 13 production external modules are grouped in the matching
`linux-p16-platform-32-drivers` package. Validation-only modules are excluded
from that installed driver package.

The exact candidate passed split-BTF validation for 8,507 modules: 8,490 native
modules, 13 production external modules and four qualification modules.
An isolated EFI/KVM boot with 4 GiB RAM and one virtual CPU passed userspace,
vDSO clock reads, signal return, fork, loading 30 selected modules, the protocol
KUnit suite and an actual call to the corrected fixed-IRQ shutdown function.
The guest completed without a kernel warning, KASAN report or failed KUnit case.
The harness run took 13.33 seconds; the host remained on its existing boot.

The tested raw kernel Image SHA-256 is
`545b659c8f5cc5c7788645693249f0d6dae35c867085657db1bafc8699604305`;
its base BTF SHA-256 is
`c0cdfcbf418a8711da781d509ad72e24d6678b9f58bdf5187670baad1c35ffa6`.
These offline results do not qualify native startup or audio/sleep with the
expanded Lockdep budget. That requires booting the complete verified kernel32
bundle and checking the real devices and logs. Kernel23 remains the default;
the successful kernel31 boot image is also retained.

The three kernel32 packages were then installed together. The installed set
passed a fresh BTF check for all 8,503 production modules. A new UKI was built
with the successful kernel31 command line and the same reference-SSDT ACPI
profile. All 430 embedded modules matched their installed counterparts and
passed BTF validation; DSP/NPU publication remains outside the initramfs.

The installed image is `/boot/EFI/Linux/omarchy_linux-p16-platform-32.efi`,
SHA-256 `2d4cfeb8a9d25d292c62c9b9f01f9c6b930a8cfcffaacfc7ea28bb1fe8eb4e75`.
Select **RTX-Spark-Audio-Kernel32** in the five-second Limine menu for the next
native test. Kernel23 remains the default/recovery; all existing UKIs, protected
kernel23/kernel31 module files, loaded drivers and the power profile matched
their pre-installation snapshots. The new native boot and its hardware tests
are still pending; the installation receipt is not a hardware qualification.

## Native kernel32 results on 14 November

The machine booted `7.2.8-32-rtx-spark-npu` successfully. Its runtime BTF hash
matched the tested bundle; NVIDIA 615.78.08, the NPU and all three DSPs were
ready, the SoundWire playback/capture card was present, and no system or user
systemd units had failed. Six baseline PCM rounds and eight exact cuDLA outputs
passed. Two complete DSP/AFE reloads then each passed the same six PCM rounds
and eight numerical outputs, using the permanent fixed-IRQ fix with no livepatch.

Clean Lockdep qualification **did not pass**. Enlarging chains alone exposed
the separate, unchanged dependency-entry limit: `MAX_LOCKDEP_ENTRIES too low`
disabled the validator during an ordinary `nvidia-smi` call. The retained stats
showed 32,714/32,768 direct dependencies, 56,064/262,144 chains,
285,277/1,310,720 chain hlocks, 379,477/2,097,152 stack entries, 2,677/8,192
classes and a maximum BFS queue depth of 683/4,096. `debug_locks` was zero.
The debug-candidate configuration now sizes entries, chains, trace storage/hash
and the BFS queue together. The normal, non-debug configuration is unchanged.
This source correction is not a clean native Lockdep result.

The direct-sysfs device-only PM attempt stopped during userspace freezing:
`jq` waited in `de_thread()` and the freezer timed out after 20 seconds.
No DSP sleep cycle completed, and the test selection was restored to `none`.
The validator now brackets a synchronous `suspend.target` transaction, whose
oneshot dependency completes before clearing `pm_test`; a timed-out or otherwise
unresolved submission retains device-test mode rather than permitting a late
real suspend. This revised orchestration remains hardware-unqualified.

Later, after USB dock removal, a normal logind/systemd suspend request at
10:05:32 was the last recorded activity of that boot. No subsequent resume,
persisted panic, NVIDIA Xid or compositor core dump was found in that journal.
This does not identify the blocking stage or establish working system sleep.
The subsequent kernel32 boot succeeded again. Further host sleep trials are
deferred while this incomplete suspend is investigated. The retained EFI boot
console and the verbose console level forced by the Lockdep capacity failure
are additional diagnostic conditions to account for; reducing console output
does not by itself establish a suspend fix.

## Isolated regressions and the exec/freezer race

The QEMU-only module in `platform/tests/lockdep-budget` creates 300 mutex
classes and 44,850 ordered dependency pairs. EFI/KVM reproduces the kernel32
entry-budget failure; the exact kernel33 Image
`935b81297137561ded40567e2c860d45cb014f72de3eb958cc01963d468170e1`
passes every pair with `debug_locks=1` and no kernel warning. A separate
four-vCPU EFI/KVM guest boots the same Image, loads 30 matching modules and
passes the permanent fixed-IRQ lifetime probe. All 8,507 built native and
external modules pass split-BTF validation against that Image. This does not
qualify Lockdep under the physical NVIDIA/desktop workload. No native kernel33 boot or installation is implied by these build/VM results.

A separate kernel32 EFI/KVM regression runs 16 owned helpers repeatedly doing
multithreaded `exec()`. All twelve raw freezer attempts returned `EBUSY`;
all twelve attempts after freezing the helpers' cgroup succeeded. The controller in `platform/tests/freezer-exec`
runs only as guest PID 1 on QEMU. It changes neither host PM controls nor host
process groups. This reproduces the early userspace race, not the full N1X
suspend failure.

A bounded, read-only BPF trace on the workstation identified the corresponding
real process path: the Omarchy monitor watcher resolves `jq` through the user's
Mise shim before `/usr/bin/jq`. At `begin_new_exec()`, the shim's thread group
contains the leader and sixteen `tokio-rt-worker` threads. The shim is a symlink
to `/usr/bin/mise`; standalone `/usr/bin/jq` has one thread. This explains how a
command normally considered single-threaded reaches `de_thread()` during the
failed freezer test. It does not prove that the later full-sleep hang has the
same cause. No development tools or session PATH were changed.

Do not blindly enable systemd's early user-session freeze: NVIDIA 615.78.08
explicitly requests a VT switch in `nvidia-drm-drv.c`, and the kernel's
`pm_prepare_console()` performs that switch before its own freezer. A frozen
compositor may be unable to acknowledge it. The installed vendor no-freeze
drop-in is therefore retained while the VT and freezer ordering is investigated.
The normal notifier path is active (`UseKernelSuspendNotifiers=1`, no
`/proc/driver/nvidia/suspend`); legacy procfs sleep scripts are not the active
GPU PM interface here.

## Kernel33 staged for native qualification

The separately owned `linux-p16-platform-33`, `-headers` and `-drivers` packages
(version `7.2.8-33`) are installed. All 8,503 installed modules pass split-BTF
validation. Each of the 430 initramfs modules passes the same check and matches
its installed counterpart byte for byte. The legacy ACPI payload matches the
successfully booted kernel32 profile. Limine image/hash verification passed.

Select `RTX-Spark-Audio-Kernel33` for the next native check. The UKI is
`/boot/EFI/Linux/omarchy_linux-p16-platform-33.efi`, SHA-256
`81984f07f58736740ca573b231221fa65e854210d0f28fc3ac58e5e6242d2130`.
The raw Image hash is recorded above; base BTF SHA-256 is
`a8c31cc92637e78fafeedf6b266a5e12e9feb1af4b4810eaef6d64638fbace02`.

This entry removes the temporary `earlycon=efifb`, `keep_bootcon`, `efi=debug`
and `initcall_debug` arguments and uses `loglevel=4`. Other boot arguments and
the ACPI payload are preserved. Kernel23 remains the default; existing images,
including diagnostic31 and the booted kernel32, were hash-checked unchanged.
The running modules, boot ID and power profile were unchanged. The previous
menu, protected-file hashes and transaction records are backed up under
`/var/lib/p16-platform/kernel33-20261114`.

At installation time, native kernel33 boot, continuous Lockdep validation,
post-reload and suspend/resume checks were pending. The subsequent native
results are recorded below. VM results and a
verified installed bundle do not establish these hardware outcomes. No further
host sleep attempt was made, and temporary build/install sleep inhibitors ended
with their owned processes.

## Native kernel33 results on 14 November

At 13:38 local time, `7.2.8-33-rtx-spark-npu` booted into the desktop. Runtime
BTF matched the installed bundle, the loaded maintained module srcversions
matched the candidate, all three DSPs and the NPU initialized, and the retained
EFI boot console was absent. The power profile was `quiet` throughout.

Lockdep remained enabled before, during and after the measured functional and
reload matrix. Its final retained counters included 41,606/262,144 direct
dependencies, 116,293/524,288 chains, 744,402/2,621,440 chain hlocks,
490,435/8,388,608 stack entries, 2,962/8,192 lock classes and a maximum BFS
queue depth of 856/16,384. `debug_locks=1`; there were no new KASAN, Lockdep,
Oops, call-trace or NVIDIA Xid warnings during the passing matrix. This is
bounded native workload evidence, not indefinite or KCSAN qualification.

The **first** baseline request did not pass: playback/S16_LE returned an ALSA
I/O error, with `soc_dai_trigger()` reporting `-EBUSY` on DL0 START. No DSP
retained error was present afterward; inspected PCM streams were closed. A
separate instrumented one-second request passed with matching endpoint
parameters and zero endpoint, DSP START and AFE START return codes. No driver
source, power profile or boot configuration was changed to obtain that result.
The original failure was not reproduced, so its precise cause remains open.
The optional [read-only START trace](../experiments/audio-start-trace/README.md)
is retained for targeted investigation; tracing itself changes timing.

A separate full **untraced** baseline then passed six three-second playback,
capture and duplex cases in S16_LE/S24_LE, plus eight independently checked
cuDLA numerical outputs. Two complete DSP/AFE unload/reload cycles then each
passed the same six PCM cases and eight cuDLA outputs. That is 18 passing PCM
rounds and 24 numerical outputs, in addition to the separately recorded failed
first request and successful traced request. Both reloads used the permanent
kernel fix, with no livepatch or reboot. The SoundWire card reappeared within
24 ms at each explicit post-reload readiness check. The boot identity and power
profile were unchanged, and the maintenance journal was removed after success.

The desktop-level follow-up found a separate UCM configuration defect despite
those direct ALSA passes. The internal card existed in PipeWire but had only
`off`/`pro-audio` profiles. WirePlumber logged `Failed to enable UCM device
Speaker`. The installed board overlay included a four-CS35L56 profile, while
SoundWire enumeration and ALSA controls showed exactly AMP1 and AMP2; AMP3/AMP4
controls were absent. `n1x-dsp-ucm` 0.1.0-3 instead includes the installed vendor
two-amplifier profile and retains output exclusivity. With that candidate in a
private UCM tree, the actual libasound calls to select HiFi and enable/disable
Speaker all returned zero. The package was then installed and both packaged
files matched the maintained sources. After restarting WirePlumber, the internal
card automatically selected `HiFi (Mic, Speaker)` and exposed its speaker sink
and microphone source. No manual profile selection was needed. A second
WirePlumber restart reproduced that automatic profile and both nodes.

A user-session PipeWire duplex check passed: three seconds of digital silence
were sent to the internal speaker sink, while the internal microphone source
produced 327,680 captured bytes, including 281,790 nonzero bytes. Both DSP
clients were active during the check, firmware PCM counters advanced, and the
clients returned to idle without retained faults. There were no new ASoC,
KASAN, Lockdep, Oops or NVIDIA Xid warnings in the checked journal window.
Capture samples remain private and were not published. Silence verifies the
playback data path, not audible speaker quality or all physical endpoints.
The USB dock sink, webcam source, other card profiles, boot identity and `quiet`
power profile were preserved. No kernel/driver replacement or reboot was
needed. This UCM defect does not establish the cause of the earlier PCM START
`EBUSY`.

No host suspend was requested during that initial matrix. The later device-only
cycle is recorded below; real s2idle, complete physical endpoint qualification
and the initial intermittent START failure remain open. Test sleep inhibitors ended with their owned jobs.
The post-run service check also exposed an unrelated `snapper-cleanup` failure:
`limine-snapper-sync` could not find its inferred target title `Omarchy` in the
custom menu. That maintenance configuration was not changed by these tests.

## Kernel33 device-only PM and NVIDIA lock ordering

At 15:52 local time on 14 November, a controlled `pm_test=devices` transaction
returned through suspend and resume. The controller ran in `system.slice`,
switched from VT1 to unused VT63 **before** enabling systemd's user-slice freeze,
and used synchronous `suspend.target` ordering with only `mem`/`s2idle` admitted.
This avoided the earlier exec/freezer failure. Freezing users took 11 ms;
device suspend/resume took approximately 873/540 ms, with the device-test's
five-second wait between them. No physical low-power entry was requested.

All three DSPs retained their D3 resources, accepted REINIT and returned ready
with `cycles=1`, error zero and matching checked configuration. The NPU's
checked stop and subsequent HFRP/bootstrap completed. The SoundWire card was
ready within 19 ms of the explicit post-return check. VT1, `pm_test=none`,
debug-message settings and the unchanged `quiet` profile were restored; the
owned runtime systemd overrides and trace instance were removed.

**The overall PM qualification failed.** POST triggered a Lockdep circular
dependency from the PM notifier rwsem through NVIDIA's system, NVKMS and UVM
global PM writers back to the notifier rwsem. Lockdep disabled itself; its
expanded budgets were not exhausted. The transaction actually returned, so
this warning is not evidence of an observed deadlock. Lockdep was not reset,
and no further host PM was attempted in this boot.

A subsequent user-session PipeWire duplex check passed through the internal
speaker and microphone nodes: playback/capture exited zero, capture contained
327,680 bytes including 280,653 nonzero bytes, both DSP clients progressed and
returned idle. Desktop defaults and other card profiles were preserved.
A separate detailed trace covered 18 one-second PCM cases with 72 endpoint,
36 DSP-trigger and 24 AFE START return values, all zero. Eight independently
checked cuDLA outputs, including reuse, passed after those cases. These are
post-resume functional results with **already disabled Lockdep**, not a clean
Lockdep pass. The original START `EBUSY` was not reproduced or resolved.

The [NVIDIA PM candidate](../platform/nvidia/README.md#pm-notifier-lock-ownership-candidate)
moves the retained writers into one dedicated kernel thread. The
[QEMU-only fixture](../platform/tests/pm-notifier-lock/README.md) reproduces
the original warning and tests the actual patched notifier against normal,
prepare-error, thread-creation-error, later-notifier-abort and resume-error
paths. All five final worker cases retained `debug_locks=1` and ended without
a held gate, worker or module reference. Native NVIDIA verification remains
pending; the existing DKMS package has not deployed this candidate.

The standalone audio validator now refuses its CLI PM modes with NVIDIA kernel
notifiers, because they lack the tested VT-before-freezer orchestration. The
device-PM helper also checks Lockdep before and after the transaction and fails
if it was disabled, even when the DSP resume counters are healthy. A non-debug
kernel records unavailable Lockdep rather than claiming that qualification.
Do not globally enable early user freezing, clear the validator warning or
retry real sleep in this boot to bypass the remaining gate.

## Prepare early-console evidence

The staging tool changes only the command line of an unsigned copy of the
failed test UKI. It retains the kernel, initramfs, load addresses, encryption
arguments and DSP/ACPI policy. It refuses output under `/boot` or `/efi` and
never installs an image or changes a boot selection:

```sh
python3 scripts/stage-audio-boot-diagnostics.py \
  --source /path/to/saved-failed-kernel31.efi \
  --output /path/to/new-private-diagnostics-directory
```

The output contains the candidate UKI, command line and a manifest pinning the
unchanged sections. It enables `efi=debug`, `earlycon=efifb`, `keep_bootcon`,
`loglevel=8` and a larger kernel log buffer. Initcall entry/return tracing is
printed on the console and retained in the log buffer. Initramfs messages go to the kernel log and
`/run/initramfs/init.log`; that file is not persistent across a reset. Automatic
panic reboot is disabled so visible failures remain available for inspection.
The EFI early console depends on usable firmware framebuffer metadata.
`keep_bootcon` retains it after dummy-console registration for this temporary
diagnostic boot. Visible output still depends on framebuffer availability;
this cannot guarantee a saved log if the machine locks before persistent
logging or root-filesystem startup.

Install only through a reviewed, backed-up boot transaction that verifies the
manifest and updates the Limine BLAKE2b hash. Preserve the working kernel23 and
recovery images, command lines and default selection. Capture the first visible
failure before attempting another modification. This command-line-only staging
tool gathers evidence; it does not apply the scoped kernel correction described
above.
