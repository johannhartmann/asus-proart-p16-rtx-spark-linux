# DSP audio release blockers

The candidate is not qualified for normal default-boot deployment. Firmware
acceptance, component registration and acknowledged commands do not establish
sample consumption, correct output or working suspend/resume.

## Corrected implementation defects

The following descriptions record the earlier faulty implementations. Their
source corrections are present; the versioned results below delimit hardware
coverage. They are not a list of defects still present in the current source.

### IRQ configuration uses a stale-cache model

The earlier `mt8901_is_volatile_reg()` in the audio prerequisite left
`AFE_IRQ_MCU_EN`, `AFE_IRQ_MCU_DSP_EN` and `AFE_IRQn_MCU_CFG0/1` cacheable under
`REGCACHE_FLAT`.
The live DL0 test observed the IRQ CFG1 ACK bit changing independently of Linux.
The SRAM owner's STOP path read that register and toggled bit 31 through the
cached regmap. A cached old bit could therefore request the value already
present in hardware, rather than acknowledge the current event. Read-modify-write
of shared routing registers could likewise use an outdated image.

The source correction makes shared IRQ configuration and target registers
volatile. Native playback/capture configure their IRQ on START; the DSP SRAM
owner now restores period, rate and domain on every actual START as well as
initial preparation. Checked failures block the stream. The cache/hardware
regression uses the patched native callbacks and separate hardware/cache
images, exercises stale ACK and target state, and repeats power-loss cycles.
The correction is installed in AFE `417B4A1282694D05F8C7B04` and the tested
playback lifecycle passes. Post-wake IRQ operation remains unqualified.

### Component registration is insufficient PM ownership evidence

The earlier `n1x_adsp_prepare()` exempted active clients when
`component_registered` was true.
That flag was set by component registration, before a sound card necessarily
bound the component. The same primary API was available to kernel clients
that were not managed by that card. The old callback admitted a bare primary
owner with registration true; no card or retained PCM lease was needed.

The source correction adds a typed PCM open API. The AFE validates the real
instantiated card, selected DL0/DL1 playback or UL1 capture CPU DAI, bound AFE driver and current memif substream.
The client owns an explicit card-to-DSP PM link until CLOSE, and records it
under the DSP device/mutex locks. PM prepare revalidates that card/stream
relationship and bound driver; legacy clients and incomplete grants are refused.
Failed OPEN releases its link. Offline regressions cover those refusals, idle
and active typed owners, link failures and successful CLOSE. The existing
DSP-to-AFE and secondary-to-primary ordering is preserved. This correction
is installed in DSP 0.1.22. Device-only PM reaches acknowledged D3, but the
subsequent DSP firmware restart fails as described below.

### Known service faults were omitted from readiness and PM admission

The earlier readiness predicate checked registration, boot readiness and the
boot error only. PM preparation additionally checked transport/power state,
but omitted primary registration, task, PCM and period errors. A later card
STOP or IRQ fault could also occur between preparation and the D3 callback.

The source correction uses the same retained-fault predicate for readiness,
PM preparation and the final drained pre-D3 check. It does not clear errors,
retry firmware or release memory. Actual-function tests cover every fault
with and without component registration, plus faults arriving after prepare.
This software correction does not establish working sample transfer or qualify sleep.

## Playback data path

The former host trigger fix enabled DL0 and produced a moving DMA cursor,
but the 0.1.19 firmware consumer and ALSA pointer stayed at zero. A nonzero
pattern remained only in the host ring. Transport replies echoed OPEN through
CLOSE successfully; START parameter 2 echoed task 16 rather than an error.
The firmware address-validator reconstruction below explains why transport
ACKs alone did not establish descriptor admission.

With DSP 0.1.22 and AFE `417B4A1282694D05F8C7B04` on kernel
`7.2.8-31-rtx-spark-npu`, both S16_LE and S24_LE now sustain 48-kHz stereo
playback. Each two-second run advanced ALSA to 96,256 frames and produced
94–95 consumed-position notifications. Two read-only snapshots per format
found matching nonzero host/AFE ring extents and hashes. The guarded operating
window is `0xfe000000..0xff000000` (exclusive end). Nine normal restart cycles,
three reopens and three normal underrun/recovery sequences passed, with all
retained service/transport/period errors still zero. Mixer gains were restored
exactly. These measurements qualify sample transfer to SRAM and the tested
lifecycle, not every analog endpoint or power state.

## Confirmed resume defect and source correction

On 2026-11-11, boot `76a1c35d`, `pm_test=devices` acknowledged D3 for all
three DSPs and restarted the NPU provider. After DSP D0 the startup descriptor
words were arbitrary values instead of retained contents. All three DSPs
reported protected `-EIO`, IRQ disabled and zero completed sleep cycles. ALSA
endpoints disappeared. The test restored `pm_test=none`; no physical standby
or subsequent PM attempt was made on that boot.

The earlier implementation incorrectly treated D0 as firmware restoration.
Native `nvadsp.sys` D0-exit function `0x140007630` sets context byte `0x239`.
First-activation dispatch `0x140003510` then calls `0x14004e000`, which rewrites
startup DRAM base/size, sends REINIT IOCTL `0x150218` with its image ID and waits
for fresh ready. `nvsrootmbx.sys` function `0x140031760` expands this to SROOT
command `0x1a`, three words `(image_id, 0, 1)`. Binary hashes are recorded in
[provenance.json](../platform/dsp/provenance.json).

The 0.1.23 correction uses a typed provider export bound to the uploaded image,
requires both the canonical loader reply and a fresh DSP-ready event, and
permits only one REINIT per provider PM generation. No general reset or raw
command API is exposed. Startup-config readback occurs before firmware starts;
pre-D3 SRAM contents are no longer mistaken for a firmware-liveness test.

After success, firmware task registrations are invalidated, while ALSA handles,
card links, operating DRAM and AFE allocations remain owned. Normal PCM prepare
re-registers the retained slices, opens tasks 7/16 or 23/21 and replays cached HW_PARAMS.
Closing before preparation sends no commands to the fresh, unopened tasks.
Offline tests cover the reconstruction and failures at every request; hardware
qualification of this new DSP/provider pair is still pending.

## Additional qualification gaps

- Trace the complete selected Windows route, including optional gain and QoS
  owners and derived stream wrappers. The native START can manage a hardware
  gain owner separately. Whether that owner is required or bypassed on the
  selected Linux DL0 route remains unproven.
- Verify audible speaker/headphone output and microphone capture. Nonzero S16_LE
  and S24_LE patterns now match at the host/AFE SRAM boundary, but this does
  not qualify every analog codec route or recording endpoint.
- Extend the passed short playback/lifecycle tests to sustained use and
  concurrent ordinary capture; assess every negotiated format/route separately.
- Qualify device-only PM testing, real/repeated s2idle, post-wake audio and NPU
  numerical execution with the corrected ownership/cache and REINIT bundle.
  Equal retained mailbox words do not establish firmware liveness.
- Lockdep disabled itself after exhausting its configured entry budget on the
  current debug boot. This is not a successful lockdep run. Hardware-independent
  sanitizer tests and module compilation do not replace kernel qualification.

Offline inspection of the exact signed HiFi1 image identified separate ITCM
and DTCM payloads and literal references to the shared-DRAM overflow diagnostic
and consume-notification function name. The standard Ghidra Xtensa decoder
cannot decode all HiFi FLIX instructions (see the
[upstream decoder report](https://github.com/NationalSecurityAgency/ghidra/issues/6342)).
The public Zephyr HiFi1 objdump resolves the required scalar FLIX bundles.
The reconstructed `is_adsp_addr_valid` proves a separate implementation defect:
the live `0xff000000 + 16 MiB` operating window overflows the firmware's 32-bit
exclusive-end addition. The validator rejects both host and SRAM addresses
before descriptor access, despite successful transport ACKs. Source 0.1.22
keeps an unadvertised guard page inside the ordinary coherent DMA allocation,
checks its advertised end, and balances the complete allocation on failure.
See [the exact image, PCs and reproduction commands](../platform/dsp/protocol.md#hifi1-shared-dram-exclusive-end-constraint).
The rejection was established offline and the guarded allocation subsequently
restored hardware sample transfer and consumed-position notifications. Other
routes and power states still require their own qualification.

The local Cadence reference corpus contains NatureDSP HiFi3/3z and HiFi5
sources and HiFi5 NNLib sources. `NDSP_HiFi5s_V310.zip` additionally contains
1,332 relocatable objects with symbols. Their `.xtensa.info` identifies
`hifi5s_ao_7`, config IDs `0xc0038286`/`0x2d0b75ad`, and RJ-2024.4. These
provide source/binary pairs for decoder validation; they do not establish
that the MT8901 HiFi1 has the same instruction encoding. The NNLib compatibility
header explicitly handles HiFi1, but the archives do not provide its generated
ISA decoder or the MediaTek audio task/IPC firmware source. The build guides
require a separately installed core configuration and toolchain.

A bounded read of the ACPI-described HiFi1 DTCM host aperture returned only
zeros across its 384 KiB extent while the firmware still acknowledged normal
task requests. This view provides no usable firmware log or heap snapshot;
it is not evidence that the running firmware's internal DTCM is empty. The
temporary read-only diagnostic was unloaded and issued no firmware commands.

## Source correction validation

DSP 0.1.22 and the matching AFE module build with `W=1` against kernel
`7.2.8-31-rtx-spark-npu` without warnings. The 14 existing DSP export CRCs
remain unchanged; the typed PCM API is additive. Driver protocol/sanitizer
checks pass, as do 126 repository unit tests (two skipped). Patch replay is
exact, and package versions and source checksums agree. The exact pair subsequently passed the playback tests above. Real sleep,
complete endpoint coverage and post-wake audio/NPU execution remain release
blockers.

The normal default boot and recovery must stay preserved. Another test boot
is useful only when it exercises a reviewed correction with explicit pass/fail
criteria for the complete affected path.


## 0.1.24 complete duplex source candidate

The 0.1.23 bundle booted all three DSPs on boot `384ed0c0`, kernel 31, without
retained faults. No PM test was run on that boot. Its successful startup does
not qualify the REINIT correction. The newer 0.1.24 source adds HiFi5 capture,
DL1 playback rebind and same-open HW_FREE/HW_PARAMS; it requires the matching
AFE and PCM client ABI 3. Both read-only frontend options default off.

Reconstruction of the selected Windows path also found two defects before
hardware deployment: endpoint IRQ routes were conflated with task-core enums,
and the shared descriptor encoder hard-coded playback direction/threshold.
The corrected targets are HiFi1 `0xa000` and primary HiFi5 `0x9d04`; capture
uses direction 2 and threshold 0. Tests verify the transmitted bytes as well
as registration, START/STOP, every uncertain ACK stage, retained reconstruction,
DMA-copy ordering, ARM release/acquire pointer publication and recoverable
capture overrun.

The capture graph is host 23 / processing 21 with six DRAM message slices and
samples at offset 8192. The two direction owners retain at most 32 KiB SRAM
each, plus playback's separate 2 KiB IPC. Capture notifications are IRQUL 0x13
with producer pointer +0x38. No speculative consumer IPC or unproven processing
tables are sent. Internal and headset codec selections, audible outputs,
duplex use and post-wake audio/NPU still require hardware qualification;
beamforming/noise suppression are not established capabilities of these tasks.

`scripts/validate-dsp-audio.py` assembles the complete pre/post-device-PM PCM
sequence and private evidence. It refuses the old module version, active
owners and retained errors, and restores `pm_test=none` on failure. This avoids
requesting a separate reboot for each additional stream feature. Physical
sleep and long-running use follow only after the full device-only pass.


The 0.1.24 source passes the complete driver/sanitizer suite and 148 repository
unit tests (two skipped). DSP and AFE build with W=1 for kernel 31 without
warnings; the 15 DSP and 17 AFE existing export CRCs are preserved. Generated
patch replay and package input hashes agree. These checks qualify the source
bundle, not capture or suspend on hardware.


## 2026-11-11 boot acc75220: desktop profile and capture START

DSP 0.1.24 and AFE `537B927FCEADD3EADCDE612` booted with all three firmware
instances ready and all retained errors zero. A 3-second S16_LE 48-kHz stereo
silence playback completed with 142 real DSP notifications and no retained
fault. Audible analog output was not assessed. Lockdep again exhausted its
entry budget during container startup, before qualification.

The stock UCM offered simultaneous Speaker and Headphones mappings. ACP's
verbose probe opened DL1 and then rejected DL0 (`EOPNOTSUPP`) because the DSP
frontend owns one playback stream. The board UCM overlay now declares the
outputs mutually exclusive while including all original vendor routing. ACP
then discovers four HiFi profiles; the internal Speaker/Mic combination is
available. After installing the package and reloading idle WirePlumber, real
speaker and microphone nodes reappear. This does not qualify microphone data.

The first S16 capture failed at START with `EBUSY` and produced zero bytes.
Bounded kretprobe tracing identified the exact return: PREPARE saw IRQ CFG0
`0x9d80=0x2a0`; all four native DSP START commands succeeded; then CFG0 was
`0x2a1`, so the host's second IRQ-programming attempt returned `-16`.
Read-only BTF/MMIO inspection at that point showed IRQ reload `0x80000400`,
HiFi5 target `0x100`, MCU/other DSP targets clear for IRQ8, enabled UL1 CON0
`0x10332a48`, and the correct retained ring `0x1a6c8800..0x1a6d07ff`.
Firmware had already activated capture. Normal STOP/CLOSE completed; no DSP,
transport, period or power fault was retained. No PM test followed the failed
capture, and no live module was reset or replaced.

AFE 0.1.25 replaces the duplicate capture activation with eleven checked reads
of IRQ metadata/targets, memif enable and ring bounds. It never rewrites the
active capture configuration. Tests cover every mismatched/read-failed check,
retained terminal errors, no register writes and repeated native capture
adoption/STOP. Playback keeps its established host trigger. Capture, duplex
and REINIT hardware qualification remain pending for this corrected AFE.


For this follow-up, the complete driver/sanitizer suite passes and 132 current
repository unit tests pass (the unrelated vLLM tests moved to their own repo).
AFE 0.1.25 builds with W=1 without warnings and preserves all 17 existing
AFE export CRCs. Its source is still awaiting fresh-boot capture qualification.
The validator rejects earlier AFE modules before authorizing PCM/PM; it reads
0400 frontend options once through a read-only desktop polkit operation while
keeping all PCM workloads under the ordinary user account.
