# DSP audio release blockers

The candidate is not qualified for normal default-boot deployment. Firmware
acceptance, component registration and acknowledged commands do not establish
sample consumption, correct output or working suspend/resume.

## Confirmed implementation defects

### IRQ configuration uses a stale-cache model

`mt8901_is_volatile_reg()` in the audio prerequisite leaves `AFE_IRQ_MCU_EN`,
`AFE_IRQ_MCU_DSP_EN` and `AFE_IRQn_MCU_CFG0/1` cacheable under `REGCACHE_FLAT`.
The live DL0 test observed the IRQ CFG1 ACK bit changing independently of Linux.
The SRAM owner's STOP path reads that register and toggles bit 31 through the
cached regmap. A cached old bit can therefore request the value already present
in hardware, rather than acknowledge the current event. Read-modify-write of
shared routing registers can likewise use an outdated image.

The source correction makes shared IRQ configuration and target registers
volatile. Native playback/capture configure their IRQ on START; the DSP SRAM
owner now restores period, rate and domain on every actual START as well as
initial preparation. Checked failures block the stream. The cache/hardware
regression uses the patched native callbacks and separate hardware/cache
images, exercises stale ACK and target state, and repeats power-loss cycles.
These are offline results; the correction is not installed on the running boot.

### Component registration is insufficient PM ownership evidence

`n1x_adsp_prepare()` exempts active clients when `component_registered` is true.
That flag is set by component registration, before a sound card necessarily
binds the component. The same primary API remains available to kernel clients
that are not managed by that card. The actual callback admits a bare primary
owner with registration true; no card or retained PCM lease is needed.

The source correction adds a typed PCM open API. The AFE validates the real
instantiated card, DL0 CPU DAI, bound AFE driver and current memif substream.
The client owns an explicit card-to-DSP PM link until CLOSE, and records it
under the DSP device/mutex locks. PM prepare revalidates that card/stream
relationship and bound driver; legacy clients and incomplete grants are refused.
Failed OPEN releases its link. Offline regressions cover those refusals, idle
and active typed owners, link failures and successful CLOSE. The existing
DSP-to-AFE and secondary-to-primary ordering is preserved. This correction
also awaits hardware qualification.

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

## Unresolved data path

The corrected AFE trigger enables DL0 and its IRQ, selects the HiFi1 target
and produces a moving hardware read cursor. ALSA's hardware pointer and the
DSP consumed-position notification count still remain zero. Ordinary ALSA
writes after START advance the producer generation but do not restore progress.
Host receive-control slices remain empty during the bounded silent test.
A later bounded S16_LE pseudorandom-pattern test found 24,600 nonzero bytes
in the 32,768-byte host ring, while the entire AFE ring remained zero in two
read-only snapshots 20 ms apart. Its hardware cursor moved between snapshots.
Speaker amplifier gains were temporarily attenuated and restored exactly;
PipeWire mute/volume were preserved. This rules out using cursor movement as
evidence of sample copying. Missing task consumption, processing/gain state
and address translation still require separation; no consumed-position
notifications arrived. S16_LE/S24_LE tests with 2/4/8 periods and full-ring or
partial prefill did not restore progress.

A bounded probe of the actual transfer replies confirmed task/command echoes
for OPEN, HWPARAM, PREPARE, START, STOP and CLOSE. START's second scalar echoes
the processing task ID, so a nonzero parameter 2 must not be guessed to be an
error status. Static wrapper inspection has not established an additional
producer mailbox command. Do not add speculative commands, polling-based fake
ALSA progress or arbitrary register writes to make this test appear successful.

## Additional qualification gaps

- Trace the complete selected Windows route, including optional gain and QoS
  owners and derived stream wrappers. The native START can manage a hardware
  gain owner separately. Whether that owner is required or bypassed on the
  selected Linux DL0 route remains unproven.
- Verify nonzero sample content, signedness and valid-bit alignment for the
  negotiated format. A 32-bit container does not by itself prove that an
  S24_LE host buffer matches the firmware's sample representation. Silence
  cannot expose an alignment or gain error.
- Require sustained consumed-position/ALSA progress, underrun recovery,
  STOP/PREPARE/START and CLOSE/OPEN reuse before audible speaker/headphone and
  microphone tests. Existing successful lifecycle ACKs are a narrower result.
- Qualify device-only PM testing, real/repeated s2idle, post-wake audio and NPU
  numerical execution only after the ownership/cache defects are corrected.
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
The rejection is established offline; the new data path still needs a fresh
hardware boot to show whether further processing or notification defects exist.

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
exact, and package versions and source checksums agree. These built modules
have not replaced the live 0.1.19 DSP/AFE pair. Streaming, real sleep and
post-wake audio/NPU execution remain release blockers.

The normal default boot and recovery must stay preserved. Another test boot
is useful only when it exercises a reviewed correction with explicit pass/fail
criteria for the complete affected path.
