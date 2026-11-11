# MT8901 audio DSP

The driver implements secure loading, boot notifications, bounded task IPC and
opt-in HiFi1 playback and primary HiFi5 capture clients. The platform has
two HiFi5 cores and one HiFi1 core.
ACPI provides memory/IRQ resources and routing properties. Firmware uses the
normal firmware loader, with per-core defaults and a `firmware-name` override.
See [protocol.md](protocol.md) for wire formats and reference provenance.

Firmware startup is disabled by default. Published DSP operating DRAM, AFE
SRAM and provider/module/runtime-PM leases are retained until reboot. Task
STOP, CLOSE and IRQ disable do not establish whole-core DMA quiescence.
Shutdown and reclamation must be verified before default startup is enabled.

## Normal audio integration

The candidate exposes DSP-backed DL0/DL1 playback and UL1 capture through the existing ALSA/ASoC
sound card. Applications use PipeWire/WirePlumber or ordinary ALSA; no private
userspace DSP API is needed. The machine driver binds all three firmware-ready
DSPs as ASoC auxiliary components. Kernel PM links order the sound card before
DSPs, DSPs before their AFE SRAM supplier and DLA before SROOT. There is no
reverse AFE-to-DSP dependency.

PCM client ABI 3 supports duplex, HW_FREE/HW_PARAMS on the same open file, repeated STOP/PREPARE/START and successful CLOSE/OPEN.
One maximum 32 KiB AFE ring per direction and playback IPC slices remain owned
by the DSP and are reused across streams. New formats/periods must fit that
allocation; only the negotiated extent is programmed. Rebinding requires the
same UL1 capture or an idle DL0/DL1 playback endpoint, a retired ALSA pointer
and disabled IRQs/memifs. Failed or uncertain
firmware operations remain terminal; they never free published memory.

The optional `n1x-adsp-audio.service` prepares isolated DMA domains before
loading `n1x_adsp` with automatic firmware startup. It verifies firmware-backed
ASoC readiness afterwards and performs no userspace firmware upload, unbind,
reset or unload. Its kernel-command-line condition keeps it inactive on the
ordinary boot unless that boot explicitly enables automatic DSP audio.

Microphone capture and headphone/codec controls retain the existing ALSA
and UCM interfaces. `dsp_capture=1` selects primary HiFi5 tasks 23/21 on UL1.
This implements the native non-RAW capture transport; beamforming and noise
suppression are not proven firmware capabilities. This is not a SOF firmware port. See [the audio setup and validation
guide](../../docs/audio.md) for the complete installation and exact limits.

## System sleep

Published firmware retains its runtime-autosuspend guard. The opt-in
`enable_retention_sleep` candidate permits s2idle using the existing platform
D3/D0 requests with `sys_trans=1`. Hibernate and deep sleep remain rejected.
With the option absent, published instances reject sleep in `prepare` before
any audio device suspends.

An active primary client is admitted only through `n1x_adsp_primary_open_pcm()`:
the AFE validates its instantiated card and actual DL0/DL1 playback or UL1 capture substream, and the
client owns an explicit card-to-DSP PM link. Prepare rechecks the live binding;
component registration alone and legacy/raw clients cannot grant PM admission.
The link is released at CLOSE, including terminal failures; retained fault
predicates still block D3 after a failed operation.

Prepare freezes new work but permits the typed task STOP needed by ASoC.
After ASoC has stopped streams, DSP suspend freezes all IPC, disables and
synchronizes the IRQ and drains power work. Pending mailbox packets and an
unstopped stream reject the transition. Acknowledged D3 permits SRAM/provider
votes. The AFE saves its SRAM only after all retention-capable owners voted,
then its normal runtime-PM code powers down the domain. DSP operating DRAM,
SRAM allocations, IOMMU mappings and every provider/module/PM lease remain
retained. This is a retention protocol, not DMA reclamation.

On wake the AFE powers up and restores SRAM before DSP D0. DLA restarts from its
cached firmware before its clients resume. **D0 alone does not restart the DSP
firmware.** The 0.1.22 device-only PM test lost the shared SRAM configuration
on all three DSPs and correctly stopped with a protected error state.

DSP 0.1.23 rewrites only the native startup DRAM base/size fields, then calls
`n1x_sroot_reinit_dsp_v1`. The provider sends native SROOT command `0x1a` with
three words `(image_id, 0, 1)`, bound to the previously loaded image. Both a
canonical loader reply and a fresh firmware-ready notification are required
before the provider sleep vote is released. Missing ready, pending unexplained
mailbox state, a failed D0 or an uncertain reply leave the IRQ disabled and all
memory/leases retained, with no retry.

A fresh firmware instance invalidates task registrations. The next normal PCM
prepare recreates playback tasks 7/16 or capture tasks 23/21 and replays cached HW_PARAMS using the same retained
buffers. The ALSA owner and card PM link survive; closing before preparation
retires the owner without sending CLOSE to nonexistent remote tasks. No new
buffer lease is allocated or released by this reconstruction.

The new resume path passes offline fault tests and builds for the test kernel;
**it is not hardware-qualified**. Physical sleep, post-wake playback and NPU
execution remain pending. Preserve the working boot and qualify the exact DSP,
provider, AFE/machine and kernel artifacts together. Do not replace a published
live module.

## Firmware address bounds

The HiFi1 firmware rejects every audio address if its 32-bit shared-DRAM
exclusive end overflows. DSP 0.1.22 reserves one additional, unadvertised page
inside the normal coherent DMA allocation and checks the advertised exclusive
end before publishing it. This fixes the former 16 MiB allocation at
`0xff000000`. Published operating memory is still retained until reboot.
See [the firmware validator evidence](protocol.md#hifi1-shared-dram-exclusive-end-constraint).

## Secure loading and IPC

The driver acquires SROOT client ABI v4 and the additive typed REINIT export
during probe. An older provider defers probe rather than losing resume support. Its referenced handle
selects a unique provider under the same firmware parent and establishes
DSP → DLA → SROOT ordering for system PM. Missing providers defer probe;
ambiguous associations fail closed. The current firmware has no `_DEP` or
`_DSD` association for these devices, so sibling uniqueness is a platform
fallback, not a binding for arbitrary future boards.

Before taking power or allocating DRAM, boot reserves that provider. Before
the first DSP DMA address write it makes the reservation permanent. Failures
before publication cancel the reservation; published instances retain it even
if the later image upload fails. Successful staging release uses ABI v2's
canonical-reply rules. SROOT authenticates signed images; the host validates their
container structure and bounds. A canonical completed upload may release its
temporary image staging, independently of the retained DSP lifetime lease.
Malformed or uncertain uploads retain staging and block further submissions.

Requests use checked packets, nonzero transaction tokens and serialized
mailbox ownership. ACKs and asynchronous notifications have separate matching
paths. Slot/ACK waits are bounded. Unexpected replies, timeout, power failure
or uncertain ownership make the channel terminal. No raw userspace command
interface is provided.

Readiness and sleep admission reject retained boot, transport, power and
primary-service errors, including faults observed after PM preparation. A ready
component still does not establish card binding or PCM progress. The remaining
[PM ownership, IRQ-cache and data-path blockers](../../docs/audio-review.md)
prevent production qualification.

## Playback

The client supports route 2 with primary task 7 and processing task 16. Task 7
uses boot-owned coherent DRAM. Task 16 uses two AFE-owned 1 KiB IPC slices,
registered before OPEN. HWPARAM configures the host, hardware and bridge rings;
PREPARE orders AFE ring programming, four task descriptors and IRQ preparation.
START runs processing before primary; STOP reverses that task order before
stopping the owned IRQ. Failures retain published memory and stop the sequence.

The AFE DL0/DL1 frontend uses the existing DPCM/DAPM/SoundWire routing. Its read-only
`dsp_playback` parameter defaults to false. ALSA's managed buffer is copied into
the coherent host ring on producer ACK. Consumed-position notifications drive
the pointer and complete-period accounting; workqueue delivery handles periods
and errors outside hard IRQ. Close synchronizes listeners and drains work
before retiring borrowed substream pointers.

The frontend requires the matching [AFE owner](afe/README.md) and provider ABI.
Route 3 capture uses four host message slices plus two processing slices in
boot-owned DRAM, with samples starting at offset 8192. Native IRQUL command
0x13 reports the producer pointer at packet offset 0x38. Work copies completed
bytes to ALSA staging before publishing the capture pointer. DMA-copy overruns
produce recoverable XRUNs; transport faults remain terminal. Native direction
2 and zero start threshold are used throughout the capture graph.

Capture, DL1 switching, corrected IRQ targets and complete-stream hardware
qualification remain pending. Offline tests do not qualify audible playback or shutdown.

## Build and tests

```sh
make -C platform KDIR=/usr/lib/modules/$(uname -r)/build W=1 -j2
python3 -m unittest discover -s tests -v
cd platform/dsp && makepkg
```

`Kbuild` supports external/DKMS builds and `CONFIG_N1X_ADSP` integration.
Actual-function sanitizer harnesses cover PM preparation and boot serialization,
IPC, task/PCM transitions,
producer/period handling, faults and concurrency. Native KUnit protocol tests
are described in [platform/README.md](../README.md). Do not replace a published
live module to validate a new package; qualify changed sources after a reboot.
