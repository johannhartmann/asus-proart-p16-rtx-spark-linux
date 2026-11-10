# Kernel driver architecture

The local drivers provide hardware enablement and experimental firmware
services. They are not collectively ready for mainline submission. A working
desktop, successful module build, or passing protocol test does not establish
safe suspend, device removal, firmware recovery, or support on another board.

## Subsystem boundaries

| Component | Interface and ownership | Upstream direction and remaining work |
| --- | --- | --- |
| SPI HID | Existing HID transport; ACPI resources, HID/IIO sensor clients | Submit the small [SPI HID series](../upstream/spi-hid/README.md) against the HID maintainer tree, rather than introducing a second transport. Preserve deferred IRQ probing, matching replies and IRQ/workqueue lifetime. |
| Ambient light | Existing `hid-sensor-als` IIO driver, descriptor-specific channel scales | A focused IIO/HID fix or backport. Drop the replacement module once the running kernel contains the required behavior. |
| SPBM/MTEL hwmon | Standard hwmon power/temperature/limit channels; separate NVDA8800 and NVDA8810 protocols | `drivers/hwmon`, with `SENSORS_SPBM` and hwmon documentation. ACPI offsets must fit the reserved resource. N1X's fixed SoC window still needs an agreed resource-owner/binding model. Raw energy/diagnostic semantics, PM behavior and other boards remain qualification gaps. |
| SCP | Read-only debugfs snapshots and bounded queries; firmware owns startup/power | Review with MediaTek SoC/firmware maintainers. Do not claim remoteproc lifecycle support: this driver does not boot or stop the SCP. All live SRAM/mailbox readers serialize with sleep; copied snapshots outlive removal. |
| Pluton | Root-only, typed PCBI metadata queries through a reference-counted miscdevice | Review the firmware/security interface and UAPI before submission. It is not a TPM implementation. Preserve the command allowlist, canonical reply checks, compat layout and removed-device checks; do not restore the raw mailbox ioctl. |
| DSP | Signed firmware loader, IRQ/mailbox transport, typed kernel audio clients | Integrate with ASoC/SOF and the platform's firmware/power providers. Whole-core DMA quiescence is unresolved; physical state restoration remains unqualified. Default published instances refuse sleep in `prepare`. The opt-in ASoC candidate coordinates stream stop, DSP D3/D0 and SRAM retention for s2idle; hardware qualification and runtime autosuspend remain open. Leases remain retained. |
| AFE SRAM/playback | Existing MediaTek ASoC frontend, checked `gen_pool` SRAM leases, deferred ALSA period work | Keep ownership in ASoC. Complete audible-stream, error, close, suspend/resume and reclamation qualification before enabling the DSP route by default. Task STOP/CLOSE is not whole-core DMA shutdown. |
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

System sleep uses a `prepare`/`complete` gate. The DSP rejects a published
instance early. NPU preparation rejects known unsafe stop conditions and DSP
leases and prevents new submissions, diagnostic commands and DSP uploads until
completion. Completion must reopen admission when another device aborts sleep.
Runtime suspend must not silently remove power from a published firmware client.

Publication holds module and runtime-PM references. The NPU releases them only
after explicit, verified hardware shutdown. Successful startup/resume is not
permission to drop those references: a later fault may make shutdown impossible,
and `remove()` cannot veto an unload. Manual bind/unbind attributes are suppressed
while this recovery limitation remains. The service must request checked
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
leases are unchanged. The candidate provider owns per-device contexts and ABI v3 DSP handles add
DSP-to-DLA dependency ordering at probe. A handle reserves the provider before
DSP DRAM allocation and commits its lease before the first DSP address write.
Only unpublished reservations can be canceled. Lookup uses unique siblings in
the firmware namespace because the captured AML provides no `_DEP`/`_DSD`
association; ambiguity is an error. AFE/DSP lookups use the same scoped rule.
This does not resolve their bidirectional SRAM/audio ownership into an upstream
ASoC/SOF provider model, or establish whole-core shutdown. Use
firmware-described associations where justified; do not fabricate links between
the first globally matching ACPI devices.

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
