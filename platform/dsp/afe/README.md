# MT8901 AFE SRAM owner

These canonical sources generate `kernel/p16-afe-sram.patch`. The patch adds a
private gen_pool, opaque kernel leases and a DSP DL0 frontend to the existing
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

PCM binding validates an active, non-running playback substream, format, memif,
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

After both task STOP acknowledgements, `mt8901_afe_sram_stop_irq()` disables and
clears the owned IRQ and removes MCU/HiFi1 targets, preserving unrelated bits.
An I/O error is cached. IRQ disable does not establish DMA quiescence.

The disabled-by-default `dsp_playback` path reuses the DL0 frontend. PREPARE
configures the graph after ALSA sets runtime fields. Producer ACK copies new
frames into the coherent host ring with ring/boundary handling. Notifications
accumulate byte progress; complete periods and errors use queued work.

Close synchronizes the listener and drains work before consuming the primary
handle. `mt8901_afe_sram_retire()` clears the borrowed substream pointer while
retaining the published allocation and references. Later endpoint operations
fail without dereferencing the retired substream. Retirement is not release.

## Reproduce and validate

```sh
python3 scripts/prepare-afe-sram-patch.py --output /tmp/p16-afe-sram.patch
python3 platform/dsp/afe/test_sram.py
python3 platform/dsp/afe/test_frontend.py
python3 -m unittest discover -s tests -v
```

`base.json` pins prerequisite source bytes. Patch replay applies with zero fuzz
and compares the resulting files to the canonical owner/frontend sources.
ASan/UBSan harnesses exercise actual allocation, programming, suspend and
frontend functions with injected OS/register faults and concurrent callers.
They verify retention and borrowed-pointer retirement as well as successful
paths. Fresh-boot streaming and sleep qualification, DSP capture endpoints and
verified shutdown/release remain required. Generated integration patches still
need author-reviewed DCO sign-off before submission.


## Reopen and retained system sleep

ABI 2 playback reuses one maximum-size SRAM allocation after successful task
HWFREE/CLOSE. The old substream is retired before freeing ALSA state. Only the
DSP playback path may reopen its reserved memif; ordinary raw DMA cannot take
over the published memory. Rebind validates an idle IRQ and complete new ring
geometry within the retained capacity. STOP/PREPARE/START reprograms the IRQ
and resets cursors without allocating another ring or message pool.

The ASoC card's auxiliary DSP components provide card → DSP system-PM links;
DSP → AFE links order SRAM lifetime without a circular dependency. Each owner
declares retention capability during setup and votes only after acknowledged
DSP D3. Prepare rejects unmatched leases and freezes allocations. SRAM is saved
to a buffer allocated at AFE probe after all votes, and restored after AFE
power-up before DSP D0. A failed suspend performs its own force-resume rollback;
a failed restoration keeps the snapshot marked saved so consumers cannot wake.
All DMA/PM/module leases stay owned throughout; no STOP ACK is treated as a
whole-core release contract. This candidate still needs physical qualification.
