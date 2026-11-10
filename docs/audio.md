# Standard N1X audio integration

The desktop interface is ALSA/ASoC → PipeWire → WirePlumber. The stock
`mt8901-soundwire` UCM configuration supplies speaker, headphone, internal
microphone and headset profiles. Cirrus firmware and the machine routing fixes
are still required; use the repository's [firmware procedure](../README.md#build).
No application-specific DSP client is needed for normal audio.

## Candidate capabilities and limits

The new candidate automatically loads the signed DSP images and registers the
three firmware-ready DSPs as auxiliary components of the ASoC sound card. Its
DL0 playback frontend uses HiFi1 tasks 7 and 16. Repeated STOP/PREPARE/START,
HWFREE/CLOSE/OPEN and changes of negotiated format within the retained ring
capacity are implemented. Existing ALSA controls, DPCM/DAPM codec routes and
UCM profiles remain responsible for routing and volume.

Microphone capture uses the existing direct ALSA path. **HiFi5 microphone DSP
processing, beamforming and noise suppression are not implemented.** Registering
the HiFi5 components does not expose arbitrary DSP compute or a SOF runtime.
Published operating allocations and module/runtime-PM references stay owned;
whole-core release and runtime autosuspend are still unavailable.

The opt-in s2idle path orders ALSA stream stop, DSP D3, SRAM retention and
checked NPU stop; wake restores SRAM and the provider before DSP D0. Legacy
active clients without ASoC ordering, Hibernate and deep sleep remain blocked.
A timeout or failed restoration is terminal and retains memory. There is no
reset, forced unload or firmware retry after uncertain publication.

**This source candidate has offline coverage, not completed physical audio or
sleep qualification.** Keep the known-working boot entry and install the exact
matching kernel, AFE/machine modules, DSP and SROOT provider as a separate test
boot. Never replace an already-published live instance.

DSP 0.1.19 removes the second full-ring start gate for the explicit ALSA START.
It also compares mailbox state immediately before D3 and after D0 instead of
assuming that startup fields retain their original boot values. `sleep_status`
records the before/after words and whether the comparison ran. These are
candidate corrections; matching mailbox words alone do not establish firmware
liveness. Both streaming and sleep recovery still require physical tests.

## Build and install

The kernel recipe includes the generated
[`p16-afe-sram.patch`](../kernel/p16-afe-sram.patch). Regenerate it with
`scripts/prepare-afe-sram-patch.py` after editing the canonical files in
`platform/dsp/afe`; package source hashes must match. Build the matching DSP and
provider packages as described in [driver qualification](driver-qualification.md).
Provider ABI v4 and playback ABI v2 are required; older modules cannot be mixed.

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
The conditionally activated service/helper can be staged separately.

Do not start it against the old running DSP/provider. On the separate candidate
boot, add these kernel parameters while preserving the existing command line:

```text
n1x_adsp.auto_boot=1 n1x_adsp.enable_retention_sleep=1 snd_soc_mt8901_afe.dsp_playback=1 mt8901_acp_sdw_legacy_mach.dsp_playback=1
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

Next run `pm_test=devices`, restore `pm_test=none`, then qualify real s2idle with
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
