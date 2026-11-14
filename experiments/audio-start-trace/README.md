# Read-only PCM START trace

This optional bpftrace program records the maintained AFE/DSP playback START
path for `aplay` and `arecord`. It prints the ALSA state, expected/current endpoint
format, memif/substream ownership, IRQ reservation/readiness, sleep gates,
DSP client/task/preparation state and endpoint/DSP/AFE start return values. It reads kernel
metadata; it writes no registers, sends no firmware commands and starts no PCM
stream. It exits after 30 seconds and is never installed or started by a service.

Use the matching, already loaded DSP and AFE modules with BTF enabled. From the
repository root:

```sh
pkexec --disable-internal-agent /usr/bin/bpftrace -B line \
  "$PWD/experiments/audio-start-trace/start.bt"
```

Run the intended bounded `aplay` request separately while the trace is attached.
A tracer may hold module references: stop it before attempting module reload.
Tracing changes timing and a passing traced request does not prove a race fixed.
No raw PCM samples are printed. Compilation or attachment failure produces no
hardware operation.

The two-pointer primary prefix is intentionally private to this trace. Its
offsets were checked against the matching module's DWARF: device at 0, DSP at
8. This avoids selecting an unrelated forward-only BTF declaration with the
same structure name. Recheck the layout when changing driver revisions.

On native kernel33, the tested one-second S16_LE playback had PREPARED state,
matching 48 kHz/stereo/16-bit/1024-frame/eight-period metadata, a prepared IRQ
and zero endpoint, DSP START and AFE START return codes. This did not reproduce
the earlier untraced `EBUSY`; that initial failure remains unexplained. The
subsequent full untraced PCM/NPU and two-reload matrix passed. See the
[native record](../../docs/audio-boot-diagnostics.md#native-kernel33-results-on-14-november).

After the later device-only PM cycle, the expanded trace ran through 18
one-second PCM cases. All 72 endpoint, 36 DSP trigger and 24 AFE START return
values were zero. Eight cuDLA numerical outputs also passed. Lockdep had already
disabled itself on the separate NVIDIA PM warning, so this later functional
run is **not** a clean Lockdep qualification or a resolution of the initial
unreproduced `EBUSY`.
