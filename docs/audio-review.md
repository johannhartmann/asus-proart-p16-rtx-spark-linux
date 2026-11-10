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

This is unresolved. Model separate cache/hardware state in the tests and make
shared-register reads and updates coherent with their actual ownership. A fix
must also preserve period/rate/domain configuration across AFE power loss;
marking complete configuration registers volatile without restoring their
configuration is insufficient. Normal capture and prepared-but-not-running
playback must remain correct as well as active DSP playback.

### Component registration is insufficient PM ownership evidence

`n1x_adsp_prepare()` exempts active clients when `component_registered` is true.
That flag is set by component registration, before a sound card necessarily
binds the component. The same primary API remains available to kernel clients
that are not managed by that card. The actual callback admits a bare primary
owner with registration true; no card or retained PCM lease is needed.

This is unresolved. Admission of an active client must establish its actual
card/stream relationship and the corresponding card-to-DSP PM dependency.
A registration flag alone cannot demonstrate that ASoC will stop that client
before DSP D3. Preserve the existing DSP-to-AFE and HiFi5 secondary-to-primary
ordering, without introducing a dependency cycle. Test unbound components,
legacy clients, failed card binding, idle open handles and active ALSA streams.

### Known service faults were omitted from readiness and PM admission

The earlier readiness predicate checked registration, boot readiness and the
boot error only. PM preparation additionally checked transport/power state,
but omitted primary registration, task, PCM and period errors. A later card
STOP or IRQ fault could also occur between preparation and the D3 callback.

The source correction uses the same retained-fault predicate for readiness,
PM preparation and the final drained pre-D3 check. It does not clear errors,
retry firmware or release memory. Actual-function tests cover every fault
with and without component registration, plus faults arriving after prepare.
This software correction does not fix the two issues above or qualify sleep.

## Unresolved data path

The corrected AFE trigger enables DL0 and its IRQ, selects the HiFi1 target
and produces a moving hardware read cursor. ALSA's hardware pointer and the
DSP consumed-position notification count still remain zero. Ordinary ALSA
writes after START advance the producer generation but do not restore progress.
Host receive-control slices remain empty during the bounded silent test.
These observations do not distinguish missing task consumption from missing
notification delivery; silent DMA movement cannot prove either sample copying
or correct output.

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

The normal default boot and recovery must stay preserved. Another test boot
is useful only when it exercises a reviewed correction with explicit pass/fail
criteria for the complete affected path.
