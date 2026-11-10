# MT8901 audio DSP

The driver implements secure loading, boot notifications, bounded task IPC and
an experimental route-2 playback client for two HiFi5 cores and one HiFi1 core.
ACPI provides memory/IRQ resources and routing properties. Firmware uses the
normal firmware loader, with per-core defaults and a `firmware-name` override.
See [protocol.md](protocol.md) for wire formats and reference provenance.

Firmware startup is disabled by default. Published DSP operating DRAM, AFE
SRAM and provider/module/runtime-PM leases are retained until reboot. Task
STOP, CLOSE and IRQ disable do not establish whole-core DMA quiescence.
Shutdown and reclamation must be verified before default startup is enabled.

## Normal audio integration

The candidate exposes DSP-backed DL0 playback through the existing ALSA/ASoC
sound card. Applications use PipeWire/WirePlumber or ordinary ALSA; no private
userspace DSP API is needed. The machine driver binds all three firmware-ready
DSPs as ASoC auxiliary components. Kernel PM links order the sound card before
DSPs, DSPs before their AFE SRAM supplier and DLA before SROOT. There is no
reverse AFE-to-DSP dependency.

Playback ABI 2 supports repeated STOP/PREPARE/START and successful CLOSE/OPEN.
One maximum-size AFE ring and the processing-task message slices remain owned
by the DSP and are reused across streams. New formats/periods must fit that
allocation; only the negotiated extent is programmed. Rebinding requires the
same memif/IRQ, a retired ALSA pointer and a disabled IRQ. Failed or uncertain
firmware operations remain terminal; they never free published memory.

The optional `n1x-adsp-audio.service` prepares isolated DMA domains before
loading `n1x_adsp` with automatic firmware startup. It verifies firmware-backed
ASoC readiness afterwards and performs no userspace firmware upload, unbind,
reset or unload. Its kernel-command-line condition keeps it inactive on the
ordinary boot unless that boot explicitly enables automatic DSP audio.

Microphone capture and the headphone/codec controls retain the existing ALSA
and UCM interfaces. **HiFi5 microphone processing/offload is not implemented**;
registering the HiFi5 components does not claim that their capture algorithms
are used. This is not a SOF firmware port. See [the audio setup and validation
guide](../../docs/audio.md) for the complete installation and exact limits.

## System sleep

Published firmware retains its runtime-autosuspend guard. The opt-in
`enable_retention_sleep` candidate permits s2idle using the existing platform
D3/D0 requests with `sys_trans=1`. Hibernate and deep sleep remain rejected.
With the option absent, published instances reject sleep in `prepare` before
any audio device suspends.

Prepare freezes new work but permits the typed task STOP needed by ASoC.
After ASoC has stopped streams, DSP suspend freezes all IPC, disables and
synchronizes the IRQ and drains power work. Pending mailbox packets and an
unstopped stream reject the transition. Acknowledged D3 permits SRAM/provider
votes. The AFE saves its SRAM only after all retention-capable owners voted,
then its normal runtime-PM code powers down the domain. DSP operating DRAM,
SRAM allocations, IOMMU mappings and every provider/module/PM lease remain
retained. This is a retention protocol, not DMA reclamation.

On wake the AFE powers up and restores SRAM before DSP D0. DLA restarts from its
cached firmware before its clients resume. Failed AFE restoration blocks DSP
D0; failed DSP D0 or provider startup leaves that instance terminal with IRQ
and memory protections retained. The DSP also checks its retained DRAM-window
descriptor; that check alone does not prove firmware liveness.

The Windows power callbacks and vendor Linux wrappers motivate this candidate.
Physical state retention, streaming and power savings remain **unqualified**.
Do not replace a published live module. Preserve the working boot and qualify
the exact new kernel, AFE, machine, DSP and provider artifacts together.

## Secure loading and IPC

The driver acquires SROOT client ABI v4 during probe. Its referenced handle
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

## Playback

The client supports route 2 with primary task 7 and processing task 16. Task 7
uses boot-owned coherent DRAM. Task 16 uses two AFE-owned 1 KiB IPC slices,
registered before OPEN. HWPARAM configures the host, hardware and bridge rings;
PREPARE orders AFE ring programming, four task descriptors and IRQ preparation.
START runs processing before primary; STOP reverses that task order before
stopping the owned IRQ. Failures retain published memory and stop the sequence.

The AFE DL0 frontend uses the existing DPCM/DAPM/SoundWire routing. Its read-only
`dsp_playback` parameter defaults to false. ALSA's managed buffer is copied into
the coherent host ring on producer ACK. Consumed-position notifications drive
the pointer and complete-period accounting; workqueue delivery handles periods
and errors outside hard IRQ. Close synchronizes listeners and drains work
before retiring borrowed substream pointers.

The frontend requires the matching [AFE owner](afe/README.md) and provider ABI.
Route 3, additional DSP endpoints and complete-stream hardware qualification
remain open. Offline tests do not qualify audible playback or shutdown.

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
