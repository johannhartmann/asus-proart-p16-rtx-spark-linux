# Standard N1X audio integration

The desktop interface is ALSA/ASoC → PipeWire → WirePlumber. The stock
`mt8901-soundwire` UCM configuration supplies speaker, headphone, internal
microphone and headset profiles. Cirrus firmware and the machine routing fixes
are still required; use the repository's [firmware procedure](../README.md#build).
No application-specific DSP client is needed for normal audio.

## Candidate capabilities and limits

**Native boot verified on 13 November 2026:** kernel31 starts successfully after
repairing the split-BTF module mismatch. All three DSPs report accepted firmware,
readiness and zero errors; the internal SoundWire card is present. Six bounded
PCM tests passed: playback, capture and duplex in S16_LE and S24_LE. Keep the
working kernel23 default until the remaining lifecycle tests are qualified; see
[the boot repair and verification record](audio-boot-diagnostics.md).


The [interface matrix](platform-driver-status.md#current-dsp-interface-requirements)
records SROOT v5 plus REINIT, PCM ABI 3 and AFE SRAM ABI 2 separately.
Implemented capture/duplex transport does not establish hardware qualification.

The DSP 0.1.25 / AFE 0.1.27 candidate automatically loads the signed DSP images and registers the
three firmware-ready DSPs as auxiliary components of the ASoC sound card. Its
DL0/DL1 playback frontend uses HiFi1 tasks 7 and 16. UL1 capture uses
primary HiFi5 tasks 23 and 21; playback and capture have independent owners. Repeated STOP/PREPARE/START,
HWFREE/CLOSE/OPEN and changes of negotiated format within the retained ring
capacity are implemented. Existing ALSA controls, DPCM/DAPM codec routes and
UCM profiles remain responsible for routing and volume.

DSP 0.1.24 implements the native non-RAW HiFi5 microphone graph behind the
read-only, disabled-by-default `snd_soc_mt8901_afe.dsp_capture` option. The
internal and headset microphone UCM routes share UL1; Linux retains those codec
controls. Native Windows headset capture uses direct route 0, so routing both
Linux inputs through UL1 is a Linux integration choice requiring separate
endpoint tests. There is no evidence that tasks 23/21 provide beamforming or
noise suppression; these effects and arbitrary DSP compute are not claimed.
The secondary HiFi5 is booted and participates in PM, but has no PCM stream.
Published operating allocations and module/runtime-PM references stay owned;
runtime autosuspend remains unavailable. Explicit shutdown/reload is implemented
as an unqualified candidate with the hardened kernel power prerequisite.

The opt-in s2idle path orders ALSA stream stop, DSP D3, SRAM retention and
checked NPU stop; wake restores SRAM and the provider before DSP D0 and
a checked firmware REINIT.
Hibernate and deep sleep remain blocked. Active-client PM admission validates
the actual ALSA card/substream and owns a card-to-DSP PM link; component
registration alone is insufficient.
A timeout or failed restoration is terminal and retains memory. There is no
reset, forced unload or firmware retry after uncertain publication.

**Playback to the AFE SRAM is hardware-verified. The 0.1.22 device-only PM test
failed. DSP 0.1.23 subsequently booted all three cores successfully; REINIT
resume, 0.1.24 duplex/IRQ changes and complete analog endpoints remain unqualified.** Preserve the known-working boot entry
and install the exact matching kernel, AFE/machine modules, DSP and SROOT
provider as a separate test boot. Never replace an already-published live
instance.

DSP 0.1.22 fixes a firmware address-validation failure: the former
`0xff000000 + 16 MiB` shared-DRAM extent overflowed the firmware's 32-bit
exclusive end and caused audio descriptors to be rejected. The driver keeps
one unadvertised page in its normal coherent allocation. The tested HiFi1
window starts at `0xfe000000` and ends at `0xff000000`; see the
[firmware validator evidence](../platform/dsp/protocol.md#hifi1-shared-dram-exclusive-end-constraint).
The matching AFE owns memif/IRQ triggering, reads shared IRQ state without a
stale cache, and restores period/rate/domain on each actual START.

The tested kernel is `7.2.8-31-rtx-spark-npu`, DSP source version
`DE3B0DAE3C1469277AB6669`, AFE `417B4A1282694D05F8C7B04`. At 48 kHz stereo,
S16_LE and S24_LE each advanced ALSA by 96,256 frames over approximately two
seconds, with 94–95 consumed-position notifications and no retained DSP, PCM,
period, transport or power fault. Two snapshots per format showed matching
nonzero host/AFE extents and FNV-1a hashes: 32,768 bytes / `3c699dc5` for S16,
65,536 bytes / `6ac9ddc5` for S24. Speaker amplifier gains were attenuated for
this test and restored exactly; desktop mute and volume were preserved.

Three CLOSE/OPEN runs each passed three STOP/PREPARE/START cycles with partial
and full prefill. Each also passed a deliberate ALSA underrun (`EPIPE`) and
normal `snd_pcm_recover()` followed by resumed progress. These results verify
the playback data path and lifecycle. They do not establish audible output,
microphone processing, physical suspend or post-wake operation. The debug
kernel exhausted its lockdep entry budget during container startup before the
audio tests; this is not a clean lockdep qualification.


## DSP 0.1.25 / AFE 0.1.27 native PCM verification

On 13 November 2026, the repaired `7.2.8-31-rtx-spark-npu` boot completed all
six three-second PCM tests using DL0 playback and UL1 capture at 48 kHz stereo.
Both S16_LE and S24_LE passed playback, capture and concurrent duplex. DSP
notification/counter checks advanced, capture byte counts matched the requested
duration, and all four capture files contained nonzero data. No retained DSP
fault was reported. Mixer controls, desktop services, modules, boot files and
the selected power profile were unchanged by the validator. Raw captures remain
private and are not included in this repository.

This qualifies the tested PCM transport on that boot. Audible speaker/headphone
output, microphone identity/quality, jack switching, device PM, physical suspend,
NPU numerical execution and DSP unload/reload were not tested in this run.
Lockdep had already exhausted `MAX_LOCKDEP_CHAIN_HLOCKS` during a Btrfs
transaction and disabled its validator; these results are not a clean lockdep
qualification. No new kernel or reboot was requested to alter that debug limit.

## Resume correction awaiting hardware qualification

The first device-only PM test (`pm_test=devices`) on 2026-11-11 acknowledged
DSP D3 and provider restart, but all three shared-SRAM startup descriptors were
lost after DSP D0. The retained-config check returned `-EIO`, left IRQs disabled
and kept DMA/provider leases. Audio endpoints disappeared. `pm_test` was reset
to `none`; physical standby was not attempted or retried on the faulted boot.

Native `nvadsp.sys` function `0x14004e000` reveals the missing step: first
activation after D0 rewrites the startup descriptor and requests firmware
REINIT, then waits for a new ready event. DSP 0.1.23 implements this through the
typed provider export `n1x_sroot_reinit_dsp_v1` (provider package >=0.1.0-11).
It accepts only a canonical loader reply plus a fresh DSP-ready notification,
then rebuilds the task graph lazily on the next PCM prepare with the existing
allocations. A failed or uncertain operation remains terminal.

The new path passes offline transition, reply/ready timeout, repeated-cycle,
retained-buffer reconstruction and terminal-fault tests. It must still pass a
fresh boot, device-only PM and post-wake audio/NPU tests before real s2idle.
These source results do not establish working suspend.

## Build and install

The kernel recipe includes the generated
[`p16-afe-sram.patch`](../kernel/p16-afe-sram.patch). Regenerate it with
`scripts/prepare-afe-sram-patch.py` after editing the canonical files in
`platform/dsp/afe`; package source hashes must match. Build the matching DSP and
provider packages as described in [driver qualification](driver-qualification.md).
Provider ABI v4, its additive REINIT export and PCM client ABI v3 are required; older modules cannot be mixed.

The single-playback DSP client also needs the small board-specific UCM package:

```sh
test -r /usr/share/alsa/ucm2/MediaTek/mt8901-soundwir/HiFi-cs42l43-cs35l56x4.conf
(cd platform/dsp/ucm && makepkg -si)
```

It adds a board master and a verb that includes the installed vendor codec
routes and declares Speaker/Headphones mutually exclusive. It replaces no
vendor-owned file, so package updates retain the overlay. Without a DSP ASoC
supplier the master falls back to the stock topology dispatcher. The existing
vendor profile is required (provided here by `omarchy-settings-dev`). On an
idle desktop reload WirePlumber with `systemctl --user restart wireplumber`.
PipeWire otherwise probes both playback PCMs concurrently, exceeds the single
playback owner contract and discards the entire HiFi profile. This rule does
not implement two simultaneous DSP playback streams.

AFE 0.1.26 distinguishes the two hardware START contracts. HiFi1 still needs
host memif/IRQ activation. HiFi5 capture already enabled its hardware after
native task START: the AFE verifies the active IRQ's rate/domain/count,
exclusive processor target, enabled memif and all base/end address words.
It adopts only an exact match and performs no live reconfiguration; mismatches
and read errors remain terminal. Before firmware START, PREPARE clears only the
owned capture IRQ's default MCU route while the IRQ is verified disabled.
After an AFE power cycle, cached address/IRQ preparation is invalidated even
for an idle prepared stream. Failed handoff and START validation log the exact
register/read error and expected value. This correction is built/offline-tested but
needs fresh-boot capture and duplex qualification.

Install PipeWire, WirePlumber, `alsa-ucm-conf`, ALSA tools, the board's Cirrus
firmware and the locally prepared signed N1X firmware packages. After hardware qualification, the DSP DKMS
package also installs `n1x-adsp-audio.service` and its small domain/readiness
helper. Enable the service for subsequent boots:

```sh
sudo systemctl enable n1x-platform-npu.service n1x-adsp-audio.service
```

For an existing installation, stage modules only in the candidate kernel
namespace and retain the old kernel’s module files. Do not globally upgrade
DKMS packages before qualification if that would rebuild the preserved kernel.
The conditionally activated service/helper can be staged separately. Run
`depmod` with a normal installation umask (022); generated module indexes must
remain readable so ordinary `modinfo` and dependency checks work. Keep capture
files and test reports private independently of those system metadata files.

Do not start it against the old running DSP/provider. On the separate candidate
boot, add these kernel parameters while preserving the existing command line:

```text
n1x_adsp.auto_boot=1 n1x_adsp.enable_retention_sleep=1 snd_soc_mt8901_afe.dsp_playback=1 snd_soc_mt8901_afe.dsp_capture=1 mt8901_acp_sdw_legacy_mach.dsp_playback=1
```

Also blacklist `snd_sof_mt8901` for that boot so the placeholder SOF driver does
not claim the DSPs. If `module_blacklist=` already exists, append the module to
its comma-separated list. Keep the packaged `blacklist n1x_adsp`: explicit
service loading occurs only after the three isolated IOMMU groups have been
validated/prepared. The service is conditional on `n1x_adsp.auto_boot=1`, so it
stays inactive on the preserved ordinary boot. It initializes firmware in the
kernel and verifies readiness; it never performs userspace firmware uploads,
unbinds a driver, resets hardware or unloads a published instance.

IOMMU domain selection requires both `CAP_SYS_ADMIN` and `CAP_SYS_RAWIO`.
The service retains those capabilities and `CAP_SYS_MODULE`; it uses a closed
device policy and blocks raw-I/O syscalls. `PrivateDevices` must remain off
because systemd removes `CAP_SYS_RAWIO` when that option is enabled.

The automatic path runs before `multi-user.target`. PipeWire and WirePlumber
then see a normal sound card. Use normal desktop sound settings for output,
microphone and jack selection. No separate per-user DSP service is needed.

## Qualification after the fresh boot

Record the kernel release, module source versions and matching build manifest.
First check:

```sh
systemctl status n1x-platform-npu.service n1x-adsp-audio.service
cat /proc/asound/cards
wpctl status
for device in /sys/bus/platform/devices/NVDA830{1,2,3}:00; do
  cat "$device/asoc_ready" "$device/status" "$device/sleep_status"
done
```

All three ASoC readiness values must be 1 with error-free accepted firmware.
Verify that the internal card is using its normal UCM HiFi profile and that
PipeWire exposes playback and microphone nodes. Do not route full-range audio
to raw speaker-band PCMs; preserve the existing board tuning and start at low
volume. Check real speaker/headphone output, jack switching, internal and
headset microphone capture and ordinary PipeWire client close/open/recovery.
A successful playback command is insufficient: DSP consumed-data/period
counters must advance, and real audio must be confirmed.

Use the bounded validator for DSP 0.1.25 with AFE 0.1.27, with a known microphone
stimulus and both raw PCMs idle. It runs S16_LE/S24_LE playback, capture and
duplex, then optionally device-only PM and the complete PCM sequence again:

```sh
python3 scripts/validate-dsp-audio.py --output /path/to/new-private-audio-results --device-sleep
```

Playback uses silence and preserves all mixer/desktop settings; this tests the
transport, not audibility. Capture files and reports are private (0700/0600),
remain local and may contain microphone audio. The script never stops another
client. An occupied PCM or a retained fault stops qualification. The PM step
opens the desktop polkit dialog, uses `pm_test=devices` rather than physical
sleep, and restores `pm_test=none` even on failure. All-zero capture fails rather
than passing a nonfunctional input. Test headphones separately with
`--playback hw:CARD=mt8901soundwire,DEV=1`, using a new output directory, and
qualify both microphone selections through the normal UCM controls. One playback
stream and one capture stream are supported concurrently; simultaneous DL0 and
DL1 DSP playback is not implemented. Each direction retains a maximum 32 KiB
ring, with a separate 2 KiB playback IPC lease; later geometry must fit.

After device-only PM passes, separately verify numerical NPU execution. Only
then qualify real s2idle with
idle and running playback/capture. Check uninterrupted endpoint recovery,
repeated reopen, retained allocation counts and numerical NPU execution after
each wake. Do not initiate these tests during an active working session.
Record failures instead of resetting or force-unloading a published device.
Physical state retention and power savings cannot be established by compilation,
sanitisers, SRAM simulation or a `pm_test` pass.

Before device sleep tests, inspect `/proc/driver/nvidia/params`. The installed
615.78.08 open driver uses `UseKernelSuspendNotifiers: 1` and
`PreserveVideoMemoryAllocations: 1`; it performs memory preservation through
its kernel PM notifier. Disabled legacy `nvidia-suspend`/`nvidia-resume` units
alone do not indicate a missing sleep path in that configuration. Older or
proprietary drivers require checking their own power-management documentation.
The NPU provider retains validated firmware and immutable VBIOS policy in CPU
memory so its resume does not depend on filesystem or display-locator access.

Without the candidate parameters, the existing direct audio path remains the
baseline. Successful hardware qualification is required before making the new
DSP path the default boot.


## Module reload qualification

The initial load of the new bundle still requires a matching kernel boot:
DSP 0.1.25, AFE 0.1.27, provider package 0.1.0-12 / ABI v5, and
`p16-dsp-shutdown-power.patch`. A running 0.1.24 module cannot gain a shutdown
callback by replacing its file. Do not force-unload that older instance.
The patch preserves the normal SSPM boot and power-management path and adds a
checked transport for DSP shutdown. Any submitted SET timeout, including an
ordinary client's timeout, prevents further checked shutdown commands until
reboot. Rebind or ordinary recovery cannot clear that history. Mailbox-busy
before submission remains retryable; no old acknowledgement may authorize
reclamation.

First run the complete playback/capture/duplex validator against the freshly
booted bundle. Then perform two reload cycles, with numerical NPU validation and
the same six PCM tests after each cycle. The reload command intentionally
interrupts the caller's PipeWire/WirePlumber services and restores their prior
state; it does not stop other users or arbitrary ALSA applications:

```sh
pkexec --disable-internal-agent /usr/libexec/n1x-adsp-audio --reload
python3 scripts/validate-dsp-audio.py --output /path/to/new-private-reload-results
```

The helper performs a group quiesce before memory release. Its per-core
`shutdown` state reports native completion and resource retirement; this is
not an independent physical power-state sensor. The implementation follows
NVIDIA/MediaTek's [MT8901 device-abandon power contract](https://github.com/NVIDIA/NV-Kernels/blob/dd99802c8b0c384169bb36293c9517fa67238e47/sound/soc/sof/mediatek/mt8901/mt8901.c)
and the reconstructed Windows teardown ordering. Hardware qualification of that
combination remains required. Keep the known-working default/recovery boot.

New DSP/AFE module files must already be installed for the running kernel before
maintenance; the helper neither compiles nor installs code. It keeps the NPU
provider loaded so verified per-image retirement survives. System-sleep and
physical endpoint qualification remain separate gates, even after reload works.

The maintenance helper checks replacement module files, minimum versions,
kernel vermagic and dependency paths before stopping desktop audio. A private
root-owned journal in `/run/n1x-adsp-audio-reload.json` saves the invoking user,
boot identity, original module parameters, active services and completed stage.
If a software operation fails, correct the module file or service problem and
continue in the same boot:

```sh
pkexec --disable-internal-agent /usr/libexec/n1x-adsp-audio --resume
```

Continuation after complete DSP retirement does not send D3/abandon again.
If the new DSPs are already ready, a sound-card or service retry keeps that
firmware instance. An accepted upload with released staging but missing ready
may instead use another checked native quiesce/reload; a never-published core
needs no firmware shutdown transaction. Kernel provider admission and the
shared-core barrier still apply. An uncertain loader result or power completion
is never replayed, and a journal from another boot or user is refused. Success
removes the journal. This software recovery is implemented and fault-tested;
failed-boot recovery and repeated reload remain unqualified. Independent physical power-state telemetry remains unavailable.

On 13 November 2026 the first complete native DSP/AFE unload/reload succeeded
on kernel31 after correcting a fixed-IRQ borrower lifetime bug in the common
MediaTek ASoC driver. Six post-reload PCM rounds and eight independently checked
cuDLA outputs passed. The permanent kernel bundle must include
`p16-afe-const-irq-shutdown.patch`; a fixed IRQ reservation must not keep the
closed PCM's substream pointer. The initial kernel31 instance needed the narrowly
guarded temporary livepatch described in [the boot evidence](audio-boot-diagnostics.md#fixed-irq-lifetime-and-first-native-reload).
Device-only PM also passed the full twelve-round before/after PCM matrix.
Two native reload cycles and a further device-only PM cycle have now passed the same PCM/NPU checks. Real sleep and clean Lockdep remain separate gates.

Both maintenance and PM validation issue sysfs commands through a single
unbuffered write. A control write error stops the operation; buffered close-time
resubmission must never repeat a power or shutdown command. SoundWire card
re-registration is awaited before post-resume PCM opens.
