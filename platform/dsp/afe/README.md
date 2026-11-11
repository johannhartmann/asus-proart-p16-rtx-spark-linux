# MT8901 AFE SRAM owner

These canonical sources generate `kernel/p16-afe-sram.patch`. The patch adds a
private gen_pool, opaque kernel leases and DSP DL0/DL1 playback and UL1 capture frontends to the existing
AFE module. Existing DPCM/DAPM routes continue to own the SoundWire codecs.
The ordinary audio path remains available if SRAM setup fails.

## Resource and lifetime contract

Initialization validates the ASD hardware version and firmware SRAM tuple:
resource extent, CPU/VAD/DSP address alignment and 32-bit bounds. Mapping uses
`devm_ioremap_resource` without write combining. Probe neither clears SRAM nor
submits DSP commands. The native mapping reference is `nvasd` `0x140024560`;
input hashes and source metadata are pinned in the repository.

Reservations are multiples of 16 bytes and are zeroed only after obtaining
runtime PM. Each lease retains device, module and PM references. Address views
share the allocation offset; clients must use the view required by their
protocol. Releasing an unpublished lease returns its allocation and references.

Clients mark memory published before sending its address to firmware. Release
then returns `EBUSY`. Runtime autosuspend and module removal remain blocked while leases
exist. System s2idle has an opt-in, unqualified retention path described below. Publication is retained after uncertain requests. This is an interim
retention contract; verified DSP quiesce/release is still required.

PCM binding validates an active, non-running PCM substream, format, memif,
fixed IRQ and complete ring extent. Independent IPC leases derive from a bound
PCM peer but cannot bind substreams. Published IPC retains its own references
even if the original peer is released.

## Ring, IRQ and frontend

`mt8901_afe_sram_prepare()` revalidates the endpoint and programs base, inclusive
end and their MSBs through checked register writes. It uses the AFE/VAD view,
keeps the ALSA runtime allocation unchanged and does not enable the memif.
Successful repetition is idempotent; partial failure is terminal.

Endpoint ABI 2 separates ring preparation from IRQ preparation. After DSP
PREPARE acknowledgements, `mt8901_afe_sram_prepare_irq()` validates a disabled
IRQ and programs its period count, rate and active clock domain. Readiness is
reported only after every checked update succeeds. Routing and enable bits are
not changed by this preparation.

After the complete native task START sequence, the frontend asks the AFE owner to
start its published PCM lease. The owner checks the active substream, prepared
ring, IRQ metadata and sleep state. HiFi1 playback removes the MCU target and
selects HiFi1 (`0xa000`),
restores the period/rate/domain, enables the memif and enables the IRQ. Shared IRQ
configuration and routing registers are volatile because firmware/hardware
can modify them. Restoring configuration on every START also covers a prepared
stream whose AFE lost power before it started. Each update is checked and preserves unrelated
bits. A partial failure is terminal; the frontend requests normal task STOP
without retrying START or releasing published memory.

After both task STOP acknowledgements, `mt8901_afe_sram_stop_irq()` disables
the memif, disables and clears the owned IRQ, and removes MCU/DSP targets. An I/O
error is cached. Disabling this channel does not prove whole-core DMA
quiescence or permit releasing published memory.

The disabled-by-default `dsp_playback` path reuses DL0/DL1. PREPARE
configures the graph after ALSA sets runtime fields. Producer ACK copies new
frames into the coherent host ring with ring/boundary handling. Notifications
accumulate byte progress; complete periods and errors use queued work.

The separate read-only `dsp_capture` option routes UL1 through primary HiFi5.
Its IRQ worker copies only firmware-produced bytes to ALSA staging, publishes
the pointer after copying, and reports XRUN on a pending/in-flight ring overrun.
Capture performs no playback producer publication. Two 32 KiB PCM rings and
playback's 2 KiB IPC lease fit concurrently in the shared 80 KiB pool.

Close synchronizes the listener and drains work before consuming the primary
handle. `mt8901_afe_sram_retire()` clears the borrowed substream pointer while
retaining the published allocation and references. Later endpoint operations
fail without dereferencing the retired substream. Retirement is not release.

## Reproduce and validate

```sh
python3 scripts/prepare-afe-sram-patch.py --output /tmp/p16-afe-sram.patch
python3 platform/dsp/afe/test_sram.py
python3 platform/dsp/afe/test_frontend.py
python3 platform/dsp/afe/test_irq_cache.py
python3 -m unittest discover -s tests -v
```

`base.json` pins prerequisite source bytes. Patch replay applies with zero fuzz
and compares the resulting files to the canonical owner/frontend sources.
ASan/UBSan harnesses exercise actual allocation, programming, suspend and
frontend functions with injected OS/register faults and concurrent callers.
They verify retention and borrowed-pointer retirement as well as successful
paths. Fresh-boot duplex/endpoint and sleep qualification and
verified shutdown/release remain required. Generated integration patches still
need author-reviewed DCO sign-off before submission.


## Reopen and retained system sleep

PCM client ABI 3 reuses a maximum 32 KiB SRAM allocation per direction after successful task
HWFREE/CLOSE. The old substream is retired before freeing ALSA state. Only the
DSP PCM path may reopen its reserved memif; ordinary raw DMA cannot take
over the published memory. Rebind validates an idle IRQ and complete new ring
geometry within the retained capacity. STOP/PREPARE/START reprograms the IRQ
and resets cursors without allocating another ring or message pool.

The ASoC card's auxiliary DSP components provide card → DSP system-PM links.
The typed PCM client also retains its own explicit card → DSP link after
validating the instantiated card and DL0/DL1 playback or UL1 capture substream; PM revalidates the binding.
Registration of an unbound component and raw clients do not grant PM admission;
DSP → AFE links order SRAM lifetime without a circular dependency. Each owner
declares retention capability during setup and votes only after acknowledged
DSP D3. Prepare rejects unmatched leases and freezes allocations. SRAM is saved
to a buffer allocated at AFE probe after all votes, and restored after AFE
power-up before DSP D0. A failed suspend performs its own force-resume rollback;
a failed restoration keeps the snapshot marked saved so consumers cannot wake.
All DMA/PM/module leases stay owned throughout; no STOP ACK is treated as a
whole-core release contract. This candidate still needs physical qualification.


AFE 0.1.25 adopts firmware-started HiFi5 capture instead of trying to program
an already-enabled IRQ. Eleven checked reads require the prepared rate/domain,
period count, exclusive HiFi5 target, enabled UL1 and exact base/end/MSB words.
A mismatch or failed read is terminal and retains the lease; there is no
fallback that rewrites an active IRQ. Actual boot evidence and the remaining
qualification boundary are recorded in [the audio review](../../../docs/audio-review.md).
