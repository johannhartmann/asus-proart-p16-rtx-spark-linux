# Kernel driver architecture

The local drivers provide hardware enablement and experimental firmware
services. They are not collectively ready for mainline submission. A working
desktop, successful module build, or passing protocol test does not establish
safe suspend, device removal, firmware recovery, or support on another board.

## Normal module startup

The production drivers are native C `.ko` modules registered with the Linux
platform/ACPI, HID/IIO, hwmon, ALSA/ASoC and DRM accelerator subsystems. Their
probe, firmware, IRQ, DMA and PM paths execute in the kernel. The N1X driver
admission rules use ACPI hardware IDs, revisions, resources, coherency and
firmware ABI validation, not an ASUS product/BIOS allowlist, `:00` instance
name or a workstation path. Register offsets and firmware image IDs describe
the supported IP/ABI; they are not interchangeable with machine-name checks.

The helper-free packaging removes the NPU/DSP startup services and their
domain-switching/readiness helpers. `n1x-translated-dma.patch` chooses DMA
domains for NVDA200A, NVDA8600 and NVDA8301/2/3 through SMMUv3's normal
`def_domain_type` callback, before binding. The other devices retain their
existing policy, including NVIDIA PCI and HiSilicon exceptions. This is needed
only because this distribution defaults IOMMU groups to passthrough; drivers
continue to reject unsuitable/shared DMA domains before publication. They do
not write their own sysfs controls or rearrange live domains.

DSP 0.1.26 declares its SROOT dependency through normal module softdeps and
defers the secondary HiFi5 probe until the primary's firmware and ASoC component
are ready. No userspace module-load order is required. Firmware uses the
standard in-kernel firmware API. Debugfs is diagnostic only and is not a boot
prerequisite. No Python program is needed for boot, audio, inference or PM.
The driver packages install no Python helper. Python reload qualification and
Pluton diagnostic tools remain in the source tree for developers, alongside
tests and optional application bindings; they are not installed kernel-runtime
components.

ASUS board-specific ALSA UCM files remain intentional: codec/amp wiring is a
machine topology description, as in ordinary upstream-supported sound cards.
They are separate from the SoC drivers and must not be replaced by a guessed
generic routing profile.

**Migration status:** kernel34 booted and passed the initial six PCM cases and
eight numerical NPU outputs with the previous startup services. The helper-free
source packages are now installed, the DSP/provider startup services are
removed and the old SDK startup service is masked. Two subsequent DSP module
reloads through ordinary udev/ACPI handling passed six PCM cases and eight NPU
outputs each with Lockdep enabled. The separately versioned SROOT DKMS source
is 0.1.1; its kernel firmware-provider ABI remains v5.

A bounded device-only suspend/resume cycle passed with fresh DSP readiness
and Lockdep enabled. This used explicit VT handoff and a temporary user-slice
freeze; it does not qualify the default sleep policy or physical sleep.
Normal-user PipeWire duplex passed afterward. A later `atop` perf read exposed
a separate circular-locking warning, disabling Lockdep. The final six PCM cases
and eight NPU outputs are functional results only; they do not establish
locking correctness. The [native evidence](evidence/helper-free-kernel34-native.json)
records these separate scopes. Full helper-free system cold boot, physical/
repeated sleep, the native locking warning and the earlier unreproduced PCM
START `EBUSY` remain open.

Kernel34 (`7.2.8-34-rtx-spark-npu`) and its matching DSP 0.1.26/provider ABI 5
module set have completed offline qualification. The exact kernel passed an
EFI/KVM boot, userspace/vDSO signal and fork checks, 30 module loads and the
AFE IRQ-lifetime regression. A separate VM retained Lockdep across 44,850
ordered dependency pairs. All 17 external modules passed split-BTF checks
against the candidate Image. The DSP and provider package payloads contain no
startup service or libexec helper and have no Python runtime dependency.
The [artifact record](evidence/helper-free-kernel34-offline.json) pins the
source revisions, module identities and package hashes. These checks do not
qualify native ACPI coldplug or physical sleep. Installed-module BTF checks covered
8,503 modules; all 430 embedded modules match the installed files. The previous
ACPI profile and boot arguments were preserved. The normal `Omarchy-P16` entry
now selects the tested kernel34 image; the old entry is retained as
`Omarchy-P16-Previous`, and recovery/prior image files are unchanged. The
separate `RTX-Spark-Kernel34` entry remains available. No power-profile change
was made. Selection and image validation do not substitute for observing the
next complete boot through the new startup configuration.

The native locking trace joins an NVIDIA I2C notifier path with a platform-bus
IOMMU notifier path. Those heads share a Lockdep class in this kernel. The
[QEMU model](../platform/tests/bus-notifier-lock/README.md) reproduces a
cross-head warning with shared classes, avoids it with per-head classes and
still detects a same-head positive control. This supports a classification
explanation; it is not a fix or proof that the complete native graph is safe.
No Lockdep reset or driver-core annotation patch was applied to the host.

## Subsystem boundaries

| Component | Interface and ownership | Upstream direction and remaining work |
| --- | --- | --- |
| SPI HID | Existing HID transport; ACPI resources, HID/IIO sensor clients | Submit the small [SPI HID series](../upstream/spi-hid/README.md) against the HID maintainer tree, rather than introducing a second transport. Preserve deferred IRQ probing, matching replies and IRQ/workqueue lifetime. |
| Ambient light | Existing `hid-sensor-als` IIO driver, descriptor-specific channel scales | A focused IIO/HID fix or backport. Drop the replacement module once the running kernel contains the required behavior. |
| SPBM/MTEL hwmon | Standard hwmon power/temperature/limit channels; separate NVDA8800 and NVDA8810 protocols | `drivers/hwmon`, with `SENSORS_SPBM` and hwmon documentation. ACPI offsets must fit the reserved resource. N1X's fixed SoC window still needs an agreed resource-owner/binding model. Raw energy/diagnostic semantics, PM behavior and other boards remain qualification gaps. |
| SCP | Read-only debugfs snapshots and bounded queries; firmware owns startup/power | Review with MediaTek SoC/firmware maintainers. Do not claim remoteproc lifecycle support: this driver does not boot or stop the SCP. All live SRAM/mailbox readers serialize with sleep; copied snapshots outlive removal. |
| Pluton | Root-only, typed PCBI metadata queries through a reference-counted miscdevice | Review the firmware/security interface and UAPI before submission. It is not a TPM implementation. Preserve the command allowlist, canonical reply checks, compat layout and removed-device checks; do not restore the raw mailbox ioctl. |
| DSP | Signed firmware loader, IRQ/mailbox transport, typed kernel audio clients | Integrate with ASoC/SOF and the platform's firmware/power providers. Checked native device-abandon and DMA retirement passed two unload/reload cycles; physical power-state telemetry remains unavailable. Default published instances refuse sleep in `prepare`. The opt-in ASoC candidate coordinates stream stop, DSP D3/D0 and SRAM retention for s2idle; hardware qualification and runtime autosuspend remain open. Leases remain retained. |
| AFE SRAM/PCM | Existing MediaTek ASoC playback/capture frontends, checked `gen_pool` SRAM leases, deferred ALSA period work | Keep ownership in ASoC. Complete endpoint, duplex, error, close, suspend/resume and reclamation qualification before enabling DSP routes by default. Task STOP/CLOSE is not whole-core DMA shutdown. |
| NPU/SROOT | [Separate driver](https://github.com/johannhartmann/n1x-npu-linux), DRM compute-accelerator UAPI, component-bound DLA/SROOT endpoints | `drivers/accel`; cuDLA compatibility belongs in userspace. SROOT-owned referenced contexts and scoped DSP handles replace singleton state. Review firmware bindings and trusted-task UAPI, and establish verified whole-core release and normal remove/recovery contracts. |

The aggregate `platform/Kconfig` and `platform/Kbuild` are a convenient local
integration for builds and KUnit tests. They are not a proposal to merge all
these devices into one platform driver or to put audio, sensors and accelerators
under a single upstream maintainer.

## Lifetime and power-management contracts

Driver-managed MMIO mappings are appropriate only while the driver owns the
hardware. Probe must validate resource sizes, protocol/revision and DMA
constraints before access. Every error before publication must unwind normally.
After publication, a probe error must not release mappings still used by
firmware. The NPU therefore retains both bound components if DRM registration
fails after firmware startup; its checked shutdown path remains available.

System sleep uses a `prepare`/`complete` gate. By default the DSP rejects a
published instance early. The opt-in s2idle candidate requires checked ASoC
ownership, ordered stream stop, acknowledged DSP D3 and AFE/provider retention
votes. Provider ABI v4 permits retained DSP leases only under that protocol;
unsafe or unvoted leases still block sleep. NPU preparation prevents new
submissions, diagnostic commands and DSP uploads until completion. Completion
must reopen admission when another device aborts sleep. D0 alone does not
restore DSP firmware: the candidate requires typed REINIT and fresh readiness.
Device-only PM passed the before/after PCM matrix on kernel31. Kernel33 kept
Lockdep enabled across the bounded PCM/NPU and two-reload matrix; real s2idle
and an initial intermittent PCM START failure remain open. Runtime suspend must not
silently remove power from a published firmware client.

Publication holds module and runtime-PM references. The NPU releases them only
after explicit, verified hardware shutdown. Successful startup/resume is not
permission to drop those references: a later fault may make shutdown impossible,
and `remove()` cannot veto an unload. Manual bind/unbind attributes are suppressed
while this recovery limitation remains. Explicit maintenance must request checked
shutdown before attempting module removal; it must stop on any error.

These restrictions prevent unsafe cleanup. They are not substitutes for a
verified reset/quiesce implementation and normal removable-driver architecture.
They remain upstream blockers for the experimental firmware paths.

## Dependencies and userspace interfaces

ACPI IDs and checked firmware ABIs identify supported IP. A model name, BIOS
version, generated `:00` device name or userspace boot order is not a general
supplier binding. The shared SROOT service currently lives in the NPU module;
DSP and AFE use dynamically resolved, versioned kernel interfaces. The bound NPU
aggregate owns a stateless DLA-to-SROOT device link for system PM and shutdown
ordering; the component framework alone does not provide this ordering. The
link is established before firmware publication, remains across post-publication
failures and is explicitly removed during component unbind. Existing runtime-PM
leases are unchanged. The candidate provider owns per-device contexts. The DSP
requires ABI v5 (the v3/v4 base handle and votes, plus explicit image retirement) and the separately versioned
REINIT export. Handles add DSP-to-DLA dependency ordering at probe. A handle reserves the provider before
DSP DRAM allocation and commits its lease before the first DSP address write.
Only unpublished reservations can be canceled. Lookup uses unique siblings in
the firmware namespace because the captured AML provides no `_DEP`/`_DSD`
association; ambiguity is an error. AFE/DSP lookups use the same scoped rule.
This does not resolve their bidirectional SRAM/audio ownership into an upstream
ASoC/SOF provider model. Two native kernel33 shutdown/reload cycles passed PCM
and numerical NPU checks with Lockdep active; real sleep remains pending. Use
firmware-described associations where justified; do not fabricate links between
the first globally matching ACPI devices.

AFE/DSP PCM ABI 3 and the AFE SRAM endpoint ABI 2 are separate contracts. The
[interface matrix and hardware evidence](platform-driver-status.md#current-dsp-interface-requirements)
record their exact requirements and qualification boundaries.

Use hwmon for calibrated telemetry, IIO for sensors, ALSA/ASoC for audio and DRM
accel for inference. Do not move vendor compiler binaries or cuDLA into the
kernel. NPU task ranges and per-file result ownership do not validate every
instruction in an arbitrary firmware task image; the current device access
policy is a trusted-client boundary, not isolation for hostile jobs.

The NPU runtime/compiler and UAPI need review against DRM's open-source
userspace requirements, including the dependency on the vendor compiler. The
private Pluton ioctl and compound DSP diagnostic `status` sysfs file also need
subsystem ABI review. Per-device debugfs files retain device references and reject detached contexts.
Debugfs is suitable for diagnostics, not a required
production service API. Document accepted sysfs attributes under
`Documentation/ABI/testing` and complete UAPI comments/compat tests before
proposing those interfaces as stable upstream contracts.

## Validation and submission

Run [the offline driver checks](../scripts/check-kernel-drivers.sh) and build
with `W=1` against each supported target kernel. Package checksums must match
the actual sources. The hardware-free suite exercises actual driver functions
with ASan/UBSan, injected allocation/transport failures, malformed packets and
concurrent callers. It includes PM admission/abort and NPU post-publication
binding failures. GitHub Actions runs the platform suite; the NPU repository
has its own offline workflow.

Also run `scripts/checkpatch.pl --strict`, sparse and native KUnit in a prepared
kernel tree. Existing source-style findings must be resolved before submission;
host-test code and userspace-only headers must not be presented as kernel-source
lint results. Builds against this distribution's headers do not prove vanilla
mainline compatibility: the DSP/AFE still require matching MediaTek interfaces.

Hardware qualification must cover fresh boot, repeated sleep/resume, lid-close
abort, active/idle workloads, close while work is in flight, allocation and
transport failures, checked stop, reload and recovery. Run lockdep/KASAN/KCSAN
and DMA-API debugging on a dedicated debug kernel. Confirm firmware availability,
redistribution terms and ABI compatibility. Do not infer safe register values,
energy units or reset behavior from names alone.

Submit small subsystem-specific patches against the appropriate maintainer
trees, with kernel-style documentation and reproducible evidence. Identify
recipients using `scripts/get_maintainer.pl`; the human submitter supplies the
DCO certification and agrees to maintenance responsibilities. No maintainer
approval or upstream acceptance is implied by this repository.

References: [submission process](https://docs.kernel.org/process/submitting-patches.html),
[PM callbacks](https://docs.kernel.org/driver-api/pm/types.html),
[device links](https://docs.kernel.org/driver-api/device_link.html),
[hwmon review requirements](https://docs.kernel.org/hwmon/submitting-patches.html),
[DRM accelerator interface](https://docs.kernel.org/accel/introduction.html),
[DRM userspace requirements](https://docs.kernel.org/gpu/drm-uapi.html#open-source-userspace-requirements)
and [firmware compatibility](https://docs.kernel.org/driver-api/firmware/firmware-usage-guidelines.html).

For candidate commands, qualification evidence and the remaining hardware
boundary, see [driver qualification](driver-qualification.md).
