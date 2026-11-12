# MT8901 DSP protocol evidence

This is a static-analysis record, not a claim of hardware qualification. The
Windows drivers were imported into separate Ghidra databases and never executed.
The original binaries remain unchanged. Addresses below refer to image virtual
addresses in the pinned drivers.

## Inputs

| Driver | Version | SHA256 |
| --- | --- | --- |
| `nvadsp.sys` | 2.13.0.1 | `8b21e4652bb0ac178a2c470c8d6f982155e715c46112ac3b93de3ebfe00b13d6` |
| `nvasd.sys` | 2.13.0.0 | `a3eaa49ea54b1a7511542091efbd527000aeff4148753e68f179077c539224de` |
| `nvpep.sys` | 2.6.0.0 | `34cf1f2a9372a092555fb0887bfb76a8f205a76ff7e557224b353b09497c9bb1` |

The input hashes are pinned in `config/platform-oem.json`.

`nvasd.inf` identifies its driver as the ACX Streaming Device for `NVDA9022`.
The driver contains separate MT8195 and MT8901 implementations. Only the
MT8901 paths are relevant to this machine; the shared image also contains
Bluetooth sideband paths, which are not proof that those features are wired
on this board.

## Firmware power request

`nvadsp` function `0x140006220` dispatches notification class 2, command
`0xf005`. It reads a little-endian 32-bit value at packet offset 24 and schedules
`0x140006a70`. That worker calls `0x14004fb38`, which sends a 16-byte
`PoFxPowerControl` input with GUID
`e3b43f54-2e2d-43ae-b348-f2d3a5fc6700`:

| Input offset | Width | Value |
| --- | --- | --- |
| 0 | 8 bits | 0 |
| 4 | 32 bits | 1 |
| 8 | 32 bits | Firmware notification value |
| 12 | 32 bits | 0 |

The Linux driver queues these notifications and dispatches them from a
worker. It records the first submission error or queue overflow and performs
no further power submissions for that instance. This does not establish a
DSP shutdown contract: `0xf005` is a firmware-initiated request, not a host
shutdown acknowledgement.

## Audio request packet construction

`nvasd` function `0x140002268` constructs a 288-byte packet. Its callers clear
the backing buffer before construction. The fields directly observed in
this constructor are:

| Packet offset | Width | Observed content |
| --- | --- | --- |
| 0 | 32 bits | 2 |
| 4 | 32 bits | 16, or 16 plus inline payload length |
| 18 | 8 bits | Caller-provided IPI/channel ID |
| 19 | 8 bits | `0x10` |
| 20 | 8 bits | Caller-provided data mode |
| 21 | 8 bits | Caller-provided acknowledgement mode |
| 22 | 16 bits | Command |
| 24 | 32 bits | First parameter; inline payload length in data mode 1 |
| 28 | 32 bits | Second parameter |
| 32 | Up to 256 bytes | Inline payload in data mode 1 |

The constructor rejects data mode 1 when the payload pointer is null or the
payload length exceeds 256. It does not establish the receive-side validity
rules for firmware packets. In particular, a transmit-side constant is not
sufficient evidence to reject a firmware notification with a different field.

For acknowledged sends, `nvadsp` assigns a nonzero transaction value at packet
offset 16. Its acknowledgement matcher compares that 16-bit value. Its client
notification matcher compares the first 32-bit packet field and the byte at offset 18.
Those are separate matching paths and must not share an untyped completion.

## Mailbox slots and ownership

`nvadsp` function `0x140030000` maps the final 1024 bytes of shared SRAM as the
control area. Receive data begins at control offset `0x20`. Its mailbox
configuration literals at `0x1400504f0` contain a 288-byte slot stride and a
288-byte packet size. `0x14004aa48` queues transmit records with interrupt
index 0 and slot index 1. The transmit worker at `0x140024248` passes those
indices through `0x14004a7d8`; the copy function `0x14004a570` writes into
the shared SRAM slot, not the mailbox register aperture.

| Control-area offset | Observed role |
| --- | --- |
| `0x10` | Receive-slot ownership word, released by the host after copying |
| `0x14` | Transmit busy word, checked and set by the host before publication |
| `0x20` | Receive packet, 288 bytes |
| `0x140` | Transmit packet, 288 bytes; receive base plus one slot stride |

`0x14004b2b8`, called from `0x14004f898`, installs the transmit busy-word pointer.
The transmit worker sets that word before copying, then the mailbox helper
publishes the interrupt after a barrier. The INF pins inbound status/set to
mailbox offset `0x100`, outbound status to `0x104`, and outbound clear to
`0x10c`. Interrupt index zero uses bit zero of the inbound set register.

The Linux `n1x_adsp_transfer()` kernel client API serializes each request
through ACK completion and TX-slot release. It assigns a nonzero token, marks
the busy word, copies the complete packet, orders the writes, then rings bit 0.
The IRQ routes class-0, ACK-mode-2 packets to the transaction completion and
routes class-2 notifications independently. Only the assigned token completes
the request. An unexpected ACK, timeout, power failure or unreleased slot makes
the channel terminal; another request cannot overwrite uncertain state.

Each slot wait and the ACK wait is bounded to five seconds. Signal interruption
before acquiring the request lock performs no hardware operation. Once the
request is published, the bounded ACK wait is uninterruptible. Failure leaves
the caller's reply unchanged. The published boot state retains the module,
runtime-PM and DRAM references on every transport result.

`test_transport.py` compiles the actual transfer, receive and exported API
functions against fault-injected OS edges under ASan/UBSan. It checks literal
SRAM publication order, maximum inline data, distinct notification/ACK classes,
wrong tokens, duplicate and late ACKs, completion at the timeout boundary,
slot-release failures, power failures, invalid inputs and two concurrent
clients. `test_driver.py` also checks ACK routing through the actual IRQ and
waking a pending transaction on power-worker failure or queue overflow.

A timeout or ACK does not establish that firmware has stopped reading any DRAM
buffer described by the request. There are no userspace raw-command endpoints,
no automatic service request. Service clients must validate service replies and obey their memory and
stream lifetime contracts before releasing buffers.

## MediaTek audio service reference

The official OnePlus MediaTek source at pinned commit
`2cc7f4606b65a9ede42030ee82614dd845b665a1` contains
`audio_ipi/include/audio_playback_msg_id.h`, `audio_messenger_ipi.h` and
`sound/soc/mediatek/audio_dsp/audio_buf.h`. Their full sparse-checkout paths are
recorded in `config/platform-sources.json`.

The public message IDs identify command 5 as `AUDIO_DSP_TASK_MSGA2DSHAREMEM`
and command 6 as `AUDIO_DSP_TASK_MSGD2ASHAREMEM`. The Linux `adsp_task_init()`
registers each direction with an inline `struct audio_dsp_dram`. On ARM64 that
record is 32 bytes: three u64 fields `phy_addr`, `va_addr` and `size`, followed
by `vir_addr`. The OEM MT8901 buffer allocator at `nvasd` `0x1400249e8` fills
the same first three fields and its registration routine `0x140025020` sends
32-byte payloads for commands 5 and 6.

The public inner IPI header also matches the offsets of the OEM packet's
16-byte inner header: task/channel, layer byte, data type, ACK type, command
and two parameters. Important differences remain: the public magic is
`0x8888`, while the OEM transport assigns its transaction token there; payload
limits and layer values differ. The Windows wrapper adds another 16 bytes.
The public command list does not define OEM commands `0x20a` and `0x20b`.

These matches identify service roles and record layouts. They do not establish
that an arbitrary Linux DMA allocation or host virtual address belongs in that
record. The OEM client obtains and maps platform-provided memory regions,
initializes private pools, and translates pool addresses before registration.
The primary-task DRAM ownership and translation are established below. The
AFE stream-buffer mapping remains a separate requirement for audio streaming.

## HiFi1 shared-DRAM exclusive-end constraint

The signed HiFi1 image SHA256
`434660b36f4e21cb794bc50e10a47b91882710cbe90cb60620111a2a753c5b94`
contains `is_adsp_addr_valid` at DSP PC `0x4ff89968`. The routine reads the
shared base and size through `0x4ff96adc` and `0x4ff96ad0` (words 0 and 1
of `0x4ff4d7b0`), adds them in a 32-bit register, then branches at
`0x4ff89980` only if the exclusive end is at least the base. Otherwise it
logs `shared_dram_end ... overflowed` and returns false. This check precedes
both host-DRAM and SRAM address admission. The later SRAM ranges include
`0x4e217000..0x4e27ffff` and `0x1a6c0000..0x1a6d3fff`.

The audio descriptor handler calls this validator at `0x4ff89df1`, before
reading the descriptor. A valid mailbox/task ACK is therefore insufficient
proof that a descriptor was consumed. The original Linux allocation
`0xff000000` plus `0x01000000` bytes wraps its firmware exclusive end to zero;
even the otherwise valid AFE SRAM address then fails this validator.

DSP 0.1.22 allocates one extra page through the ordinary coherent DMA API,
with the same 32-bit coherent mask. Only the original operating extent is
advertised to firmware. Because the whole allocation must fit the DMA mask,
its unadvertised trailing page keeps the firmware exclusive end representable.
The driver also checks that end explicitly and frees the complete allocation
on every pre-publication failure. It does not reserve private IOVAs, change
coherency, resize the advertised firmware window or relocate published memory.
Tests exercise both 16/24 MiB operating extents and 4/16/64 KiB page sizes,
reject the original boundary case, and replay the reconstructed HiFi1 address
predicate against the guarded host and AFE addresses. Working live audio still
requires testing the new allocation after reboot.

The decoder used for this bounded instruction proof is the public
[Zephyr SDK 1.0.1 HiFi1 toolchain](https://github.com/zephyrproject-rtos/sdk-ng/releases/tag/v1.0.1),
ARM64 Linux asset `toolchain_gnu_linux-aarch64_xtensa-nxp_rt700_hifi1_zephyr-elf.tar.xz`,
SHA256 `e811df2431737f7429629db8432c7de5005bf34f14b305a865d17126855c65c0`.
It decodes the required six-byte scalar FLIX bundles, unlike the standard
Ghidra Xtensa placeholder. This does not establish every optional MT8901 DSP
instruction. Start decoding at a verified function entry: linear binary
sweeps can lose alignment in padding or literal pools.

To reproduce the validator listing from the exact local firmware:

```sh
python3 - <<'PYCODE'
from pathlib import Path
import hashlib
image = Path('/usr/lib/firmware/nvidia/n1x/hifi1-0-mt8901-signed.bin').read_bytes()
assert hashlib.sha256(image).hexdigest() == '434660b36f4e21cb794bc50e10a47b91882710cbe90cb60620111a2a753c5b94'
Path('hifi1-itcm.bin').write_bytes(image[0xa24:0xa24 + 0x23290])
PYCODE
xtensa-nxp_rt700_hifi1_zephyr-elf-objdump -D -b binary -m xtensa \
  --adjust-vma=0x4ff80000 --start-address=0x4ff89968 \
  --stop-address=0x4ff899c4 hifi1-itcm.bin
```

## Primary message buffers

The current firmware SSDT containing `ASD0` has SHA256
`6bd1b3801bc25048e2df874ed81594b3a7014df3f7f1eefc56efb935649e9131`.
It identifies `NVDA9022`, hardware version 1, endpoint mask `0x1ff`, and these
`acpi-asd-endpoint-path-config` values: speaker 2, headphone 2, microphone 3.
`nvasd` `0x140052840` maps path 2 to DSP type 3 (HiFi1) and path 3 to type 1
(primary HiFi5), then assigns endpoint task IDs at runtime. The task table is
zero-initialized image storage, rather than a static routing table. Its
constructor first marks all 41 slots unsupported before endpoint setup.

The speaker/headphone task group includes primary task 7. Both routes must
agree before Linux can prepare this shared task. The driver checks the live
firmware-node properties and the selected core; it does not use a fixed
assumption about which core implements playback.

For each DSP, OEM IOCTL `0x15202a` returns the complete common-buffer size at
offset 0, CPU mapping at offset 8 and DMA logical address at offset 16. These
come from the allocation at `nvadsp` `0x140002618`. The client pool setup at
`nvasd` `0x140023550` initializes an allocator over that complete extent.
`0x140025fe0` translates a pool CPU address to the corresponding DSP DMA
address by adding its offset to the returned logical base. That establishes
the ownership and translation of the host message-buffer pool independently
of the separate AFE/shared-SRAM mappings.

The primary task's two predicates at `0x140023de0` and `0x140024998` require
all four 1 KiB records. The mask literal at `0x140025018` is `0x20010400`;
only tasks 10, 16 and 29 use the special SRAM allocation path. Task 7 uses its
core's host DRAM pool. Its registration payload contains four little-endian
u64 words: DMA address, host CPU address, size and zero. The fourth word starts
zero in the cleared OEM per-task record; the host address is an opaque host
field and is never exposed through the Linux status interface.

The Linux `n1x_adsp_prepare_primary()` reserves the first four 1 KiB slices of
the boot-owned shared DRAM allocation for this task. It orders their zeroed
contents before requests 5, 6, `0x20a` and `0x20b`, and checks each ACK's task
and command. Other firmware-owned regions and the AFE SRAM are not used by
this operation. Success records four completed registrations; it does not
establish stream execution or permit freeing any of those slices.

All four registrations subsequently received matching ACKs on HiFi1. A second
trial sent scalar commands 1 (OPEN), 9 (HWFREE) and 2 (CLOSE), with parameters
zero and ACK mode 1; all three received matching task/command replies. This
matches `nvasd` open at `0x1400288b0`, cleanup at `0x140028f40` and scalar
constructor `0x14002c288`. Reports are `dsp-primary-registration-live.json` and
`dsp-primary-task-live.json` in the same results directory. No HWPARAM, PREPARE
or START was sent. CLOSE does not establish whole-core DMA quiescence.

The exclusive kernel handle serializes ownership, registration and lifecycle
requests. OPEN failure prevents another open. Close consumes the CPU handle
but preserves published memory and terminal state after a failed transaction.
Raw task-7 requests are rejected by the public transport API.

## PCM descriptors

`n1x_adsp_pcm.h` encodes the 96-byte primary-playback descriptor without
publishing it or sending firmware requests. The first six little-endian u64
fields are base, end-exclusive, read, write, byte length and data count.
Read/write begin at base and data count begins at zero. Eight little-endian
u32 fields follow: container bits, sample rate, channels, direction, start
threshold, stop threshold, period frames and period count. Task 7 uses
direction 1; the native initial start threshold is period frames times period count,
with stop threshold `0xffffffff`.

The Linux ALSA path explicitly starts all three descriptors with a one-frame
threshold. ALSA has already decided when START is legal and can initially
publish less than a whole ring. A second, full-ring firmware gate can therefore
wait for frames that the host will only produce after the first consumed-data
notification. The codec preserves the native full-ring default when its
threshold override is zero and bounds explicit thresholds to the ring size.
Actual firmware consumption still requires a fresh hardware test.

The format word contains sample width in bits, not `snd_pcm_format_t`.
The native ACX getter for container bits has index 46, channels index 43,
valid bits index 47 and rate index 50 in Microsoft's
[ACX function table](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/acxfuncenum/ne-acxfuncenum-acxfuncenum).
The pinned binary's function-pointer table starts at `0x1400cc1e0`, giving
getter addresses `0x1400cc350`, `0x1400cc338`, `0x1400cc358` and
`0x1400cc370`. The container-width value passes through engine preparation,
the common stream constructor, speaker setup and context offset `0xe8`.
Instructions `0x14002b084..0x14002b088` copy it into descriptor offset `0x30`.
Thus 24 valid bits in a 32-bit container require wire width 32.

The tail bytes are hardware-buffer flag at `0x50`, hardware memif ID at
`0x51`, IRQ ID at `0x52`, and wire memory-type value 1 at `0x53` for both
buffer types. The native IRQ mapper accepts IDs 0 through 15. Host descriptors
leave memif and IRQ zero. The counter at `0x54` and ignore-IRQ byte at `0x58`
start zero in the original zero-initialized task records; the encoder also
zeros reserved bytes. It supports mono/stereo with 16- or 32-bit containers,
checks complete-period byte length and arithmetic overflow, and leaves its
destination unchanged on error. Actual endpoint format policy and address
ownership remain the caller's responsibility.

The native default allocator selector is 3. Its mode-table entry passes through
`0x140044010`, the common constructor's parameter offset `0x1d8`, stream offset
`0x218`, and the primary constructor's parameter offset `0x84` into context
offset `0x1b4`. Selector 3 selects AFE pool 0. This traces the static default;
it is not a live Windows endpoint observation. Linux uses the AFE SRAM owner for exclusive leases and address translation;
actual stream qualification remains required.

## Primary playback processing chain

The pinned `nvasd` constructor selects primary task 7 from free tasks 7..9
for the speaker/headphone route 2. `0x140027438` inserts the first free task
16..17 into that memif's processing list. Runtime routing at `0x140052840`
assigns both groups to native core enum 3 (HiFi1) on route 2. The exclusive
Linux primary API uses the first member of each group, 7 and 16. Route 3
selects a different native primary group; the task-7 API rejects it before
registration. The separate route-3 graph is described below.

The message allocator's mask at `0x140025018` is `0x20010400`. Task 16 therefore
uses SRAM message buffers, unlike task 7's boot-owned coherent DRAM. Task 16
requires host-message registrations 5 and 6, each with a 32-byte payload
`{device address, CPU address, 1024, 0}`. The processing-message selector at
`0x140024998` excludes task 16, so `0x20a` and `0x20b` are not sent to it.
Native core enum 3 uses address translation selector 2, the AFE/VAD SRAM view.
The driver reserves one contiguous 2 KiB IPC lease from the AFE owner and
registers its two slices. Publication precedes the first registration; an
uncertain reply retains the entire lease and prevents replay.

The caller provides a separate SRAM lease bound to its non-running ALSA
playback substream. The owner validates format, ring extent, memif, fixed IRQ
and substream ownership. IPC leases cannot bind a PCM substream and hold their
own device, module and runtime-PM references. Releasing an unpublished IPC
lease balances those references; publishing it blocks release and suspend.
Releasing the original PCM peer does not invalidate a published IPC lease.

After processing registrations and OPEN, the configuration sequence is:

| Task | Command | Descriptor |
| --- | --- | --- |
| 7 | 4 | Host samples in coherent boot-owned DRAM at offset 4096 |
| 16 | `0x201` | Hardware ring in AFE SRAM; hardware flag 1 and bound memif/IRQ |
| 16 | 4 | Bridge over the same AFE SRAM extent; hardware flag 0 |

Each descriptor is 96 bytes. The request's eight-byte inline payload points
to that task's first registered message slice. Task 7's slice is coherent
DRAM; task 16's slice is I/O-mapped SRAM and uses `memcpy_toio` plus a write
barrier. The driver validates all three descriptors before allocating or
publishing processing IPC memory. Host and AFE sample rate, channels and
container width must match; their period sizes/counts may differ. No resampler
or additional processing-task chain is implemented.

PCM publication transfers the caller's lease to DSP boot state and clears
its pointer. Earlier failures can leave the caller owning an unpublished PCM
lease while DSP boot state retains already-published IPC SRAM. No firmware-stage
failure retries or releases published memory. A successful close sends task 7
commands 9 and 2, followed by task 16 commands 9, `0x202` with scalar parameter
1 (playback direction), and 2. This follows `0x140028f40`. Close does not
establish whole-core DMA quiescence. The ABI 2 candidate permits a new OPEN
after successful close by rebinding and reusing the retained rings.

## Initial primary PCM prepare

Prepare revalidates the published AFE endpoint's ownership, non-running state
and format. The native record selector at `0x14002b368` chooses the first
(host) descriptor for task 7, and the second (hardware) descriptor for task 16.
The complete initial sequence is:

| Task | Command | Descriptor |
| --- | --- | --- |
| 16 | `0x203` | Hardware |
| 16 | 3 | Bridge |
| 7 | `0x203` | Host |
| 7 | 3 | Host |

The task-16 helpers are called at `0x14002a79c` and `0x14002a7a8`; the task-7
helpers at `0x14002a7c0` and `0x14002a7cc`. Both request payloads contain the
initial ring pointers and zero counters. Sample memory is preserved. Parameter
2 is zero; the separate native resume path is not implemented. All four
matching ACKs are required before marking the chain prepared. Repeated success
revalidates the endpoint without further IPC. A firmware-stage error stops
requests and retains all published rings and message buffers.

## Consumed-data notification client

`n1x_adsp_primary_set_period()` and the non-sleeping
`n1x_adsp_primary_position()` API. Position tracking starts only after all four
PREPARE acknowledgements. Before the first accepted notification, its snapshot
has `valid=false` and offset zero. Before prepare, pointer reads return
`ENODATA` without changing the caller's output. Close disables tracking before
consuming the handle; the client must not call any API with that handle after
close returns.

The native mailbox worker dispatches class 0 / ACK mode 0 to client listeners;
class 0 / ACK mode 2 completes transactions. The native playback callback at
`0x14002b9e0` handles command `0x1b` for task 7 with parameter 2 equal to zero.
It reads the host ring's read pointer at packet offset `0x30` and counter at
`0x74`. The CPU publication routines at `0x14002cc80` and `0x14002ce90` copy a
write-generation counter into their descriptor. This is not a count of elapsed
periods or a basis for an absolute consumed-byte count.

The Linux parser accepts inline data mode 1 and payload lengths 96..256 bytes,
checks the full 288-byte packet extent and ignores untrusted outer wrapper
lengths. This is the driver's bounds policy; a live stream has not qualified
that firmware envelope. It validates the read pointer against the complete
owned host-ring extent and frame alignment. An end pointer equal to the
end-exclusive boundary normalizes to offset zero. Counter values above
`INT_MAX` are rejected; a lower nonzero generation is ignored as stale, while
zero may restart the generation, matching the native callback. Equal pointers
and counters can yield another accepted notification after a ring wrap.

The native callback ignores nonzero parameter 2. The driver reports that
case as unsupported instead of assigning meanings to unverified exception
bits. A recognized malformed notification caches an error and delivers one
error callback with the last valid snapshot. No address from that packet is
dereferenced. Subsequent position reads return the error; subsequent packets
cannot overwrite the snapshot. IPC remains available for explicit stop/close
operations. Existing transport or power failures also propagate through the
position API and IRQ delivery. Status snapshots expose notification count,
byte offset, counter and the first period error under the IPC spinlock.

The listener runs outside the IPC spinlock, in IRQ context. It must not sleep
or call sleeping DSP APIs. It may call the atomic position getter. Each
accepted consumed-data message produces a listener event; the eventual ALSA
frontend must translate position changes into ALSA period progress. Direct
ALSA period delivery for a non-atomic stream must be deferred to suitable
process context. The DL0 frontend defers delivery to queued work.

A listener can be installed once, detached with a NULL callback, then replaced.
Detach clears its function/data pointers under the spinlock and waits for
in-flight IRQ handlers. Close additionally disables tracking before sending
lifecycle commands and consuming the handle. The client must drain work queued
by its own listener before freeing that work's data. Tests pause an IRQ
callback, start detach or actual close on another thread, verify it has not
returned, and allow the callback's final atomic pointer read before teardown
completes. Later IRQs cannot call the old listener. ASan/UBSan exercises the
actual C, including the real IRQ slot-release path, bounds failures, stale
packets, counter restart, wrong ACK/class/task and transport/power errors.

## Host producer publication

`n1x_adsp_primary_commit(primary, byte_offset)`. After
configure and prepare, the kernel client obtains `pcm_view`, fills samples and
commits its frame-aligned byte cursor. The caller owns availability and must
serialize writes to samples and the handle's lifetime. The API bounds the cursor
and descriptor; it does not calculate ALSA free frames from notification
counts. The frontend supplies ALSA availability accounting.

The producer encoder retains the configured host fields and changes only the
read pointer, write pointer and counter. The read pointer is the last validated
firmware pointer, preserved separately from the normalized public byte offset.
A pointer equal to the ring end remains that end address in the next producer
record. The write cursor accepts zero through the complete ring size, including
the end address, with frame alignment. This preserves the native representation;
it does not claim that every full/empty-ring state has hardware qualification.
The first publication uses generation zero; after `INT_MAX`, the next generation
is zero. Notification count and write generation have different meanings.

Commit checks ownership, configured/prepared state, transport/power/period
errors, pointer bounds, format and its publication-count limit before changing
shared memory. Local preflight errors leave samples, message memory and counters
unchanged. Under the IPC spinlock, a DMA write barrier orders completed sample
writes before copying the descriptor to the first host message slice; another
DMA write barrier precedes reporting the publication complete. An IRQ cannot
mix a new host-side read-pointer snapshot into that descriptor copy. This is
not proof of firmware-side atomic sampling of all 96 bytes.

A power failure can become visible during publication. Commit then records a
terminal task error after the descriptor may already be visible, with no
rollback or retry. All published memory stays retained. The status snapshot
reports write offset, next generation and publication count under the IPC lock.
No mailbox command, ACK or firmware-release guarantee is invented for this path.

The portable codec tests use a fixed producer wire vector, cursor/end boundaries,
truncations, alignment and counter limits. `test_producer.py` compiles the actual
commit and consumed-data handlers with OS edges mocked under ASan/UBSan. It
checks sample/message canaries, both barriers, all preflight refusals, generation
wrap, late power failure, four concurrent writers and an IRQ held behind an
in-progress publication. The pipeline test also calls the actual commit after
actual configure/prepare and verifies unchanged mailbox history. These tests
qualify the implementation offline. No producer publication was issued to a
live DSP; the complete stream and shutdown/release remain unqualified.

## Notification registration is not a wire command

`nvasd` function `0x140004e50` creates a request with command field `0xdf00`,
then submits IOCTL `0x152010`. The IOCTL value is stored at literal address
`0x14000548c` in that driver.

`nvadsp` identifies the same IOCTL through the literal at `0x14000424c`.
That branch queues a pending client notification request. It does not call
the mailbox send function. Therefore `0xdf00` in this path is a host-side
notification filter; it must not be sent to firmware as a guessed discovery
or initialization command.

The actual MT8901 audio paths construct acknowledged inline requests for
commands 5, 6, `0x20a` and `0x20b`, with 32-byte payloads. Other paths exist
for Bluetooth sideband. Their payload layouts, DMA ownership, stream state
transitions and completion rules still need to be recovered before adding
Linux audio or compute interfaces.

## Device power-down callbacks

`nvadsp` function `0x14004fd30` installs a 0x90-byte WDF PnP/power callback
table. Its first six function pointers map to the fields in Microsoft's
[`WDF_PNPPOWER_EVENT_CALLBACKS` definition](https://github.com/microsoft/Windows-Driver-Frameworks/blob/main/src/publicinc/wdf/kmdf/1.33/wdfdevice.h):

| Callback | Address |
| --- | --- |
| D0 entry | `0x1400074e0` |
| D0 entry after interrupt enable | `0x1400077e0` |
| D0 exit | `0x140007630` |
| D0 exit before interrupt disable | `0x140007900` |
| Prepare hardware | `0x14004e390` |
| Release hardware | `0x14004eee0` |

The D0-exit callback records power-state metadata. The pre-interrupt-disable
callback calls `0x140006d70` (`ADSP_Flush_Pending_Ack`) and `0x140007020`
(`ADSP_Flush_Pending_Notification`). Those functions cancel queued host
requests under their queue locks. They do not send a firmware stop packet.
Release-hardware stops the two host worker threads, unmaps register apertures
and releases operating DRAM through `DMA_OPERATIONS.FreeCommonBuffer` at
table offset `0x18` (indirect call `0x14004f0d4`). The context stores the DMA
adapter at `+0x250`, CPU pointer at `+0x258`, DMA address at `+0x268` and
allocation size at `+0x270`. This is separate from SROOT's image staging buffer.
The three DMF cleanup calls also reach host event signaling/waiting
(`0x140019c68` / `0x14003c190`); they do not establish a DSP-off acknowledgement.

Microsoft's [ReleaseHardware contract](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdfdevice/nc-wdfdevice-evt_wdf_device_release_hardware)
places normal teardown after queue shutdown, interrupt disconnection and device
power-off. It also covers failed PrepareHardware cleanup. Copying the buffer
free into Linux without reproducing the successful hardware power-off contract
would omit a framework precondition. The native callback itself is not that
contract.

These callback bodies do not establish that DMA has stopped. That guarantee
must be traced through the platform power transition and its completion
semantics before Linux may release a published buffer. The existing Linux
`mtk_pwrap_dev_suspend()` submits the configured SCMI device-state transition
to D3 through SSPM; a matching API call alone is not proof that the DSP's bus
accesses have ceased. The explicit native shutdown candidate below implements D3/abandon with a
strict transport failure policy and a shared-core barrier. Its hardware
qualification remains outstanding; it is not an independently decoded DSP
power-state query.

The OEM PEP also has a host-initiated TINYSYS GET path:
`0x140016ca8` calls `0x140043748`, whose constants at `0x1400439b8` encode
message ID 4, protocol `0x80`, flags 1 and length 16. The request carries the
configured feature and device IDs. Its reply copies three u32 words at context
offsets `0x200`, `0x204` and `0x208`. The only caller of the wrapper in this
image is device-probe handling at `0x14001ee60`; no device-power-state decoder
has been established for those words. This distinguishes a host GET command
from unsolicited notifications on the second mailbox, but provides no basis
for interpreting a reply as confirmed D3 or DMA-off. No GET request was sent
to the live SSPM during this analysis.

Use `scripts/analyze-dsp-shutdown.py --sroot nvsrootmbx.sys --pep nvpep.sys
--dsp nvadsp.sys --output NEW_DIRECTORY` to extract these pinned instruction
ranges and the release/queue-flush call sites. The optional `--dsp` input is
hash checked, like the two required inputs; no Windows code executes and no
hardware command is sent.

Occurrences of `SoftwareBreakpoint(0xf003, ...)` in the decompilation are
ARM64 trap instructions, not firmware command definitions.

## Secure-loader staging allocation

The pinned `nvsrootmbx.sys` upload routine at `0x140031c98` calls
`0x140003b08` to allocate a bounded common DMA buffer and `0x1400039b0` to
copy the firmware image into it. It submits command `0x18`, checks both the
transport result and remote status, then reaches cleanup at `0x140003e00`.

That cleanup invokes the DMA adapter operation at offset `0x18` and clears
the saved allocation size and addresses. With the ARM64 pointer layout,
Microsoft's [`DMA_OPERATIONS` definition](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_dma_operations)
identifies this operation as `FreeCommonBuffer`. The allocation call at
operation-table offset `0x110` corresponds to `AllocateCommonBufferWithBounds`.
These observations identify the lifetime of the loader's temporary image
allocation, separately from the DSP's operating DRAM allocation.

The OEM routine also reaches cleanup on failure, so its error handling is not
a sufficient Linux release contract. A Linux implementation must distinguish
a validated completed upload from uncertain submission/completion and retain
uncertain allocations. Releasing a successfully consumed image buffer also
does not establish that DSP operating memory can be released or that another
core may be powered down. The v2 API separates consumed image staging from the retained DSP lifetime
lease.

The DSP driver uses the device-bound client operations from `n1x_sroot_client_ops_v4()`,
which extends the ABI v3 handle contract.
Its upload operation preserves ABI v2 staging semantics. The provider uses
the selected SROOT context mutex, container checks and one-attempt policy, and retains its module/runtime-PM
reference before publication. It releases the temporary image buffer only when
the serialized exchange completes with command `0x18`, raw reply header exactly
`0x18`, zero payload words, and zero status/detail. It then clears the CPU/DMA
addresses and reports `staging_released`. The published lease flag stays set;
NPU shutdown still checks it before changing hardware or lifetime state.

Every rejected, malformed or uncertain exchange retains staging and poisons
the shared loader. A later v1/v2 call cannot retry or retire an old allocation.
ABI v1 retains its original behavior. The DSP client acquires ABI v4 at probe and reserves the provider before taking
power. It commits the lease before publishing operating memory, and rejects inconsistent success fields
even if a ready notification has arrived. No operating DSP DRAM or AFE SRAM,
provider lease, module reference or runtime-PM vote is released by this API.

The provider's actual-function sanitizer harness covers every prepublication
and exchange failure, noncanonical replies, all three successful images,
v1/v2 interoperation and eight concurrent same-image callers. Shutdown tests
explicitly retain the `EBUSY` guard when a published lease has no remaining
staging allocation. DSP boot tests reject every inconsistent v2 success flag
without freeing published operating memory. These are offline checks; staging
release still requires fresh-boot hardware qualification, and whole-core
shutdown/DMA release is implemented as the unqualified native-power candidate below.

## Linux AFE hardware-ring preparation

`mt8901_afe_sram_prepare()`. The existing lease bind
and publication operations did not replace the memif's previous DRAM address.
Before the first DSP PREPARE, the DSP client now asks the AFE owner to program
its published SRAM ring, checking all four base/end register writes.
Configuration rejects a missing helper before processing-memory publication.

The owner rechecks the bound, non-running substream and format, CPU DAI,
reserved memif and fixed IRQ. It passes the I/O mapping, AFE/VAD address and
complete allocation length to checked writes of the base, inclusive end and
separate MSB registers. The generic address helper ignores write errors and is
not used. Memif DMA bookkeeping changes only after all four writes succeed.
The runtime DMA allocation is unchanged; the backend must remain serialized
with setup and teardown. No memif or IRQ is enabled.
After success, repeated calls validate ownership without writing registers.
Failure after programming begins is cached and retains all published resources;
the DSP client also caches the error and sends no PREPARE or CLOSE afterward.
The selected DSP frontend owns the corresponding trigger path.

The actual-function sanitizer harness covers a nonzero allocation offset,
incorrect owners/format/IRQ, failures at each of the four address writes and
eight concurrent preparers. The PCM service harness verifies AFE preparation precedes all four
DSP PREPARE commands, that a missing helper prevents configuration publication,
and that owner errors are terminal. All results are offline; no live AFE memory
or firmware request was used.

## Ordinary stream transitions versus pause/resume

The pinned stream vtable at `0x1400b5570` selects normal START at `+0x18`
(`0x140029310`), normal STOP at `+0x20` (`0x140029a50`), pause at `+0x38`
(`0x14002ab70`) and resume at `+0x40` (`0x14002a8a0`).

For a fresh, single-user route-2 playback graph, normal START increments the
memif/DSP user counts, acquires processing-task QoS if requested, sends each
processing task command `0x0f` with scalar parameters `(0, mode)`, enables
host channel-merge/hardware-gain owners, then sends task 7 command `0x0f` with parameters
`(mode, first_processing_task)`. The mode comes from stream context `+0xbc`,
not from the memif ID or route. Normal STOP sends task 7 command `0x10` and
releases its QoS, drops the user counts, sends processing tasks `0x10` in their
configured stop order and releases their QoS, then disables those host owners.
The no-payload and scalar helpers are `0x14002c288` and `0x14002c328`.

Command `0x209` also appears in normal START's already-active-memif branch;
it is not the fresh single-user branch. Pause uses `0x206` and has a different
hardware path. Acknowledging either task transition does not prove core
quiescence or permit DMA release.

The native object at context `+0x98` is a channel merge: `0x14003d290`
constructs it using the `mt8901_afe_cm.cpp` path and a channel-merge ID below 3.
The object at `+0xa8` owns hardware gain. Its table at `0x1400ac240` enables register `0x9800`,
bit 16, which is `AFE_GAIN_DL0_CON0`. Its reference-count code identifies
`afe_memif_hwgain.cpp`. Treating either object as a generic CPU memif enable
would be incorrect. The stock Linux AFE trigger additionally
enables/disables the memif; firmware ownership of that operation must be
qualified on the selected Linux frontend. The typed task trigger
does not perform those host register writes.

## Separate IRQ preparation and endpoint ABI 2

The native speaker handler keeps a separate IRQ object at `+0x2a8`, with
vtable `0x1400b5548`. Its prepare method `+0x18` is `0x140016150`, which calls
`0x1400091d8` and the register configuration function `0x140008e80`.
The descriptor table is `0x1400ab040`, with 22 records of 64 bytes. IRQ 0 uses
counter register `0x9d44`, bits 23:0, rate register `0x9d40`, bits 8:4, and
domain bits 11:9. These match the Linux MT8901 IRQ metadata. The pinned native
IRQ-12 record reuses IRQ-11 register offsets; this anomaly is recorded, not
copied into Linux. The playback path uses IRQs 0..6.

For a fresh start, speaker handler `0x140083a10` prepares the IRQ after the
stream's configuration/PREPARE method, starts the DSP stream, then takes the
IRQ reference. DSP IRQ method `0x140026830` increments its reference count
without writing the IRQ enable or target. The stop method `0x1400268b0`
disables the last-user IRQ and clears its target. Its argument is the
endpoint route: 2 selects HiFi1 at `0xa000`, 3 primary HiFi5 at `0x9d04`,
and 4 secondary HiFi5 at `0x9d08`. Task-core enum 3 also means HiFi1 but
is a different enum; the old interpretation of this argument was incorrect. The normal stream's gain helpers cannot supply this IRQ contract.
Actual firmware START behavior still needs hardware qualification.

The driver implements the configuration step as a separate AFE-owner
operation after the four DSP PREPARE acknowledgements. It checks the current
non-running substream/DAI/IRQ and address-prepared state, verifies the exact
register layout, obtains the rate code and active memif clock domain from the
AFE owner, and rejects a period count exceeding 24 bits. It reads the IRQ
control word and rejects an enabled IRQ. Checked updates then set counter,
rate and domain in that order; target and enable bits are unchanged.

The public endpoint snapshot is ABI 2, with `irq_prepared` set only after
complete success. Both preparation helpers and ABI 2 are required before
processing-buffer publication. A failed address or firmware preparation
prevents IRQ writes. A failed IRQ update caches a terminal error; the DSP
client sends no additional firmware requests and retains its buffers. It
also checks transport/power state before and after the IRQ operation.

Actual-function sanitizer tests verify both preparation phases, all register
write failures, owner/layout/rate/domain/bounds faults, unrelated-bit
preservation, active-IRQ refusal and concurrent idempotence. The DSP harness
checks the complete order, old-ABI and missing-helper rejection, and no retry
or CLOSE after IRQ failure. These checks do not prove whole-core quiescence. No new module or hardware request was used.

## Typed route-2 START/STOP

The driver sends command `0x0f` to task 16 with scalar parameters
`(0, 0)`, then to task 7 with `(0, 16)`. It supports normal playback mode 0
after the existing OPEN/HWPARAM/PREPARE chain, one host producer publication
and a matching, published ABI-2 endpoint with IRQ readiness. It validates the
address, length, format, period geometry, memif and IRQ before the first START
request. Host DAPM, gain and channel-merge routing belong to the audio client;
the typed trigger does not duplicate the stock CPU memif trigger.

STOP sends command `0x10` to task 7, then task 16, then calls the AFE owner's
HiFi1 IRQ stop operation. For the owned IRQ, the owner clears CFG0 bit 0,
reads CFG1 and toggles its bit 31 to acknowledge a pending IRQ, then removes
that IRQ's MCU target in `0x9d00` and HiFi1 target in `0xa000`. The clear-bit
operation follows the existing MT8901 Linux AFE trigger and the separate
native IRQ-stop path. Every I/O result is checked. Other IRQ bits are preserved;
no memif enable or gain register is written.

The stop owner permits an ALSA substream still marked RUNNING during its STOP
callback, with unchanged format, DAI, memif and IRQ ownership. It clears IRQ
readiness before the first write, caches any programming failure and never
retries partial stop writes. Successful repetition writes nothing. The DSP
client detaches and synchronizes its period listener after complete success;
the caller drains work queued by that listener separately.

START/STOP transaction errors and failed IRQ cleanup are terminal and preserve
all published memory and references. Close stops a started stream before
HWFREE/CLOSE. Restart after STOP requires a fresh PREPARE, listener and sample publication
in the ABI 2 candidate; its IRQ is revalidated and reprogrammed while disabled. Neither STOP acknowledgements nor IRQ disable establish
whole-core DMA quiescence or authorize buffer release. The transitions remain hardware-unqualified.

`test_trigger.py` compiles the actual control and lifecycle functions with
ASan/UBSan. Independent wire vectors check both START scalar parameter pairs
and STOP order. Faults cover endpoint ABI/readiness/geometry, each transaction's
timeout and reply echo, late power/period errors, missing helpers and IRQ-stop
failure. Eight concurrent START and STOP callers each issue only one sequence.
The AFE harness covers every stop I/O failure, both clear-bit values, all seven
playback IRQs and preservation of unrelated target bits.

## AFE/DPCM playback frontend and borrowed lifetime

The driver integrates a DL0 playback client into the existing nonatomic
AFE/SoundWire frontend. The AFE `dsp_playback` parameter defaults to false and
is read-only after module load. The client requires `n1x_adsp_primary_abi()`
to return primary-client ABI 3 before OPEN. This contract includes retained
lease retirement and an `at_end` flag alongside the normalized consumed byte
offset. The flag distinguishes a firmware read address at the end boundary
from the base address; the firmware wire record is unchanged.

The frontend reserves/configures its hardware ring in PREPARE, after the ALSA
core assigns runtime format and period fields. The host and hardware rings use the negotiated geometry, bounded by the
firmware-described SRAM capacity after processing IPC reservations. DPCM/DAPM keeps the existing codec route. The DSP trigger replaces
the stock CPU memif/MCU-IRQ trigger on this selected path; complete-stream
hardware qualification is required to confirm firmware operation on Linux.

ALSA's managed DMA allocation is application staging memory. ACK computes the
advance from the previous ALSA application pointer across its large boundary,
rejects rewinds/advances larger than the ring, copies only the newly committed
frames into the owned coherent host ring and publishes the write cursor.
Whole-ring writes preserve the end boundary instead of publishing the base.
Pointer reads use the DSP host consumed position, not the AFE CUR register.

The IRQ listener accumulates modular byte movement, including the explicit
end boundary. It queues a period update only after a complete negotiated
period; the echoed producer generation is not used as elapsed time. Queued
work calls ALSA once for accumulated complete periods, as required by the
kernel PCM API, and reports errors in process context. Multiple complete
unobserved laps cannot be inferred from a modulo cursor; notification cadence
and overrun behavior still need hardware qualification.

Close marks the client closing, detaches/synchronizes IRQ callbacks and drains
work before freeing the primary handle. DSP close also retires the published
AFE lease's borrowed substream pointer on success or terminal task failure.
The owner retains the SRAM allocation and memif/device/module/power references;
future endpoint/prepare requests fail without accessing the old substream.
No retirement operation writes registers or establishes DMA quiescence.

Successful CLOSE/OPEN reuses retained memory and permits format/period changes
within its capacity. STOP/PREPARE/START is implemented; direct firmware pause/resume
and other DSP frontends remain unsupported. Actual-function sanitizer tests cover helper/ABI
faults, producer/boundary vectors, partial/coalesced notifications and close
against a blocked period worker. The complete path still has no hardware streaming qualification.


## System-sleep retention candidate

The pinned `nvpep.sys` device-power callback at `0x14001fb40` constructs its
SCMI SET composite as the ACPI action word OR device state shifted by 16,
the `Complete` notification phase shifted by 8 and the system-transition byte. It calls
`0x1400169d0`, then the common SET implementation at `0x1400430c0`. The matching
Linux wrapper encodes D3/complete on suspend and D0/incomplete on resume. The
candidate uses `sys_trans=1` specifically for system sleep; ordinary runtime
PM retains `sys_trans=0`. The existing `scripts/analyze-dsp-shutdown.py`
extractor now includes the pinned PEP device-power callback for reproducibility.

The callback processes D0 with `Complete=0` and non-D0 with `Complete=1`;
it skips the opposite phases. Microsoft's
[`PEP_DEVICE_POWER_STATE` definition](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/pepfx/ns-pepfx-_pep_device_power_state)
defines `Complete` as an input supplied by PoFx around the Windows driver-stack
transition, not an SSPM reply or a request to wait for physical power-off.
Likewise, the callback's handled return value is not a hardware-state result.
Linux `sspm_ci_set()` correlates the SET acknowledgement but does not decode a
power-state result. Neither a successful SET, the `Complete` bit, nor the
uninterpreted three-word GET reply permits operating-memory reclamation.
`mtk_pwrap_dev_remove()` sends action `0x05000000` (device abandon), whose name
alone provides no stronger DMA-off guarantee.

In pinned `nvadsp.sys`, D0 entry `0x1400074e0` and post-interrupt entry
`0x1400077e0` update driver state; D0 exit `0x140007630` updates state and
pre-interrupt-disable `0x140007900` flushes host queues. These callbacks contain
no DSP firmware stop/reload operation. This supports investigating platform
retention rather than inventing a STOP mailbox command. It does not prove
retention on Linux, that a SET acknowledgement means physical D3 completion,
or that operating DMA can be reclaimed.

Consequently the candidate keeps every published DSP allocation and provider
lease. ABI v4 votes order the idle-DSP D3/D0 transitions around the provider's
existing checked DLA stop/restart. The optional s2idle path rejects uncertain
uploads, poisoned IPC, legacy active audio clients lacking ASoC ordering. The automatic ASoC candidate
coordinates card STOP and retained AFE SRAM, as described below. Retained
startup-mailbox contents are compared before D3 and after D0, but firmware liveness, audio continuity,
physical sleep and power savings still require fresh-boot hardware tests.
Whole-core shutdown, full DMA release, Hibernate and deep-sleep recovery are
not implemented by this retention path.


## Automatic ASoC audio candidate

The current candidate registers firmware-ready DSPs as auxiliary ASoC
components. The card core creates card-to-component device links, ensuring
ALSA stream SUSPEND/STOP precedes DSP D3. DSP-to-AFE links order SRAM saving
and restoration without a reverse dependency. Host IPC is frozen in prepare,
except the typed task-7/task-16 STOPs required by the card. DSP suspend then
freezes every request and drains the IRQ/power work before requesting D3.

Successful task HWFREE/CLOSE permits reuse of the same retained message slices
and sample ring; this does not authorize freeing them. A new ALSA substream
may bind only after retirement, with the same memif/IRQ, an idle IRQ and a
complete ring fitting the original allocation. The processing task's registered
slices persist across OPENs. STOP/PREPARE/START uses the normal four PREPARE
messages and the original START pair, rather than substituting the separate
0x206/0x209 pause/resume protocol. Actual streaming and reconfiguration still
require hardware qualification.

Each DSP-owned SRAM lease declares retention capability during setup and votes
after acknowledged DSP D3. The AFE saves SRAM only when every owner voted;
its snapshot memory is allocated during probe. On wake it powers up and restores
SRAM before DSP D0 is permitted. A failed restoration retains the saved flag
and blocks consumers. This follows the platform's D3/D0 retention model, not a
new claim of whole-core shutdown. Runtime autosuspend and DMA reclamation stay
blocked. The opt-in HiFi5 capture graph below uses the existing ALSA input
routing; its endpoint and sleep qualification is still pending. No physical qualification is claimed by these changes.


## Primary HiFi5 capture and duplex (PCM client ABI 3)

Static analysis of the pinned `nvasd.sys` reconstructs the MICP endpoint path 3
(SSDT3 endpoint mask bit 1). `0x140006ed0` maps it to task-core 1, primary HiFi5;
this is distinct from the IRQ route enum. Microphone setup `0x1400810e8` calls
constructor `0x140027ba8`: nonzero non-RAW processing modes select host task
23; RAW GUID `9e90ea20-b493-4fd1-a1a8-7e1361a956cf` selects 22. The Linux
candidate implements 23. `0x140027438` selects processing task 21.

The allocation mask `0x20010400` excludes both 23 and 21. Host registrations
5/6/0x20a/0x20b use DRAM offsets 0..4095; processing registrations 5/6 use
4096..6143; samples start at 8192. Neither task registers IPC SRAM. Configuration,
PREPARE and CLOSE have the same command ordering as playback, with tasks 23/21.
Direction helper `0x14002aed8` returns 2 for both tasks. Configuration
`0x14002a0b0` writes this at descriptor offset 0x3c and clears the start
threshold at 0x40 for capture; playback uses direction 1. Copying playback's
constant direction/threshold would therefore produce invalid capture semantics.

The address translation helper `0x140025fe0` selects context+0x50 for selector
2 (AFE/VAD) and +0x58 for selectors 3/4 (HiFi5). Initializer `0x140024560`
populates them from the firmware SRAM tuple, defaulting to 0x1a6c0000 and
0x4e5c0000. Message allocator `0x1400249e8` maps task-core 3 to translation
selector 2, and task-core 1 to selector 3. Linux uses the corresponding AFE
lease metadata, never a guessed interchangeable DMA address.

Native capture START `0x140029310` sends:

| Task | Command | Parameter 1 | Parameter 2 |
| --- | --- | --- | --- |
| 21 | 0x0f | 0 | 1 |
| 23 | 0x1f | 21 | 0 |
| 23 | 0x11 | 0x30 | 0 |
| 23 | 0x0f | 1 | 21 |

The 0x30 selector is opaque. Its optional client-table copy is absent when the
constructor's pointer/count remain zero; no invented table is uploaded. The
last prepared host message is retained, matching that native zero-copy case.
STOP sends 0x10 to host then processing before disabling UL1 and its HiFi5 IRQ.

The native IRQUL listener accepts class 0, ACK 0, task 23, command 0x13 and a
96-byte inline descriptor. Its producer pointer is packet+0x38, rather than
playback's consumed pointer at +0x30. The native capture engine neither applies
the playback generation filter nor publishes a host consumer IPC. Linux checks
payload length, owned extent and frame alignment, then defers the DMA copy.
The ALSA pointer advances only after samples have been copied to its managed
staging ring. Pending bytes include in-flight copies; reaching a full ring
reports a recoverable ALSA XRUN. Transport or backend faults remain terminal.

The frontend owns one stream per direction. Its persistent 32 KiB playback and
capture rings plus 2 KiB playback IPC fit the 80 KiB pool. Playback may rebind
DL0 to DL1 after normal task CLOSE and checked idle old/new IRQs and memifs;
UL1 remains capture-only. HW_FREE/HW_PARAMS can reopen the same ALSA file with
new geometry without leaking leases. REINIT reconstructs either graph using
the retained buffers and card links.

The stock UCM routes both internal and headset microphones through UL1, whereas
native Windows HSMP is direct path 0. Applying the HiFi5 graph to Linux UL1 is
an integration choice requiring tests of both codec selections. No beamforming,
noise suppression, secondary-HiFi5 PCM or whole-core shutdown is inferred.
`analyze-dsp-pcm.py` emits the pinned code ranges and protocol facts without
executing Windows code. Actual-function sanitizer harnesses cover native
message values, fault stages, repeated duplex retention votes, ring wrap,
copy ordering, XRUN and recovery. These are offline results; full capture,
endpoint switching and post-REINIT hardware qualification remain pending.


## Native shutdown and reload candidate

DSP 0.1.25 / AFE 0.1.27 uses the power contract in NVIDIA/MediaTek's pinned
[MT8901 driver](https://github.com/NVIDIA/NV-Kernels/blob/dd99802c8b0c384169bb36293c9517fa67238e47/sound/soc/sof/mediatek/mt8901/mt8901.c):
device abandon transitions that DSP to D3. The Windows callback ordering above
places operating-memory release after the framework's power-off stage. The
candidate sends explicit D3 with `Complete=1, SystemTransition=0`, then abandon,
and requires successful completion of both. It does not decode an independent
physical DSP-off register. **That native API contract and the complete Linux
reload sequence still require hardware qualification.**

The hardened helper records completed stages (bit 0 D3, bit 1 abandon). Only an
unsubmitted `EBUSY` can continue the current stage; acknowledged D3 is not
replayed. The original SSPM shared-slot transport could consume a very late
interrupt after a bounded drain, including by reading back the next request's
header. The local patch records every submitted SET timeout and permanently
rejects further checked DSP-shutdown commands after one. A driver rebind or successful
ordinary transaction does not reset that history. All pre-existing platform
callers keep their original bounded-drain recovery behavior; only the new
shutdown helper uses the checked transport. This narrows completion handling
for DMA retirement; it does not turn a transport ACK into a power sensor.

Provider v5 binds an exclusive image slot before DMA publication. Its shutdown
admission freezes that image's lifetime and rejects primary-HiFi5 shutdown while
the secondary is still running. A completed native transition is recorded
without releasing memory. Reclamation waits for every published DSP image to
reach that barrier, so shared core resources remain protected. Legacy clients
without this protocol prevent retirement. System PM rejects a stopping image.
Only then can the provider clear that image's lifetime reservation and permit
future upload; the consumer separately frees its operating DRAM and AFE leases.
Failed or uncertain secure-loader transactions still prohibit retirement.

The DSP freezes IPC under its mutex, synchronizes its IRQ and drains queued
power work. Old ambiguous firmware messages are not acknowledged or replayed;
native power-off retires that transport. AFE release requires a retired ALSA
borrower and no foreign owner of the stored IRQ. It stops and reads back the
independent AFE memif before returning SRAM to the pool. Capture START and
memif STOP use hardware reads instead of cached firmware-mutated state. SRAM,
PM, module and provider references are balanced; partial software cleanup can
continue after completed power-off without repeating hardware transitions.

For a later load, only the same provider's completed retirement marker permits
replacing a stale startup DRAM descriptor. The marker is exclusive to an image
reservation. A pending unexplained mailbox still refuses boot. The maintenance
helper keeps that provider loaded and reloads only the sound-card, DSP and AFE
modules. It preserves module options and the invoking user's audio-service
state. No unbind, force unload, guessed SROOT command or register reset is used.

The locally named `sroot-v0.bin` / `sroot-v1.bin` are upload inputs for image
`0xc0302`; their payload is DLA firmware. The plaintext v1 payload contains DLA
engine and network-processing code, not the secure SROOT command dispatcher.
It supplies no DSP shutdown opcode; command-number adjacency is not evidence.
