# PM notifier lock-order model

This deliberately small, hardware-free module isolates a writer retained from
`PM_SUSPEND_PREPARE` until `PM_POST_SUSPEND`. It registers with the real kernel
PM notifier chain. It accepts only QEMU DMI plus explicit `run_test=1`, and is
never packaged or installed on the workstation.

Build against the exact debug kernel:

```sh
make -C /path/to/debug/kernel M="$PWD/platform/tests/pm-notifier-lock" W=1 modules
```

In a disposable Lockdep-enabled guest, load with `run_test=1 retain_gate=1`,
select `pm_test=freezer`, read that selection back, then write `mem` to
`/sys/power/state`. This never reaches device suspend or physical sleep. The
expected negative result is a circular dependency between `model_gate` and
`(pm_chain_head).rwsem`, followed by a completed POST with `debug_locks=0`.
Use a **fresh guest boot** for `retain_gate=0`: its PREPARE writer is scoped to
that callback, so the expected POST leaves `debug_locks=1` without a warning.
Do not reset Lockdep in either guest. Bound guest lifetime externally and
collect its serial log even when the expected assertion fails.

The scoped control does **not** implement a usable replacement for NVIDIA's
gate: unlocking while hardware is suspended would permit unsafe GPU access.
This model identifies the cross-callback pattern, not a proven hardware
deadlock, an NVIDIA fix, or successful physical suspend. It cannot exercise
NVIDIA private code, GPU clients, other notifier interactions or firmware.

## Test the patched notifier

The worker variant includes the **actual notifier extracted from patched vendor
source**, with only the hardware power function replaced by the model gate.
It uses real kernel threads, completions, module references and PM notifiers.
Prepare a new fixture for each case:

```sh
python3 platform/tests/pm-notifier-lock/prepare-owner.py \
  --source /path/to/pristine/nvidia-615.78.08 \
  --kernel /path/to/debug/kernel --output build/pm-owner-normal --case normal
```

Cases `normal`, `prepare`, `thread`, `late` and `resume` cover a complete cycle,
failed preparation, failed thread creation, another notifier aborting after
preparation, and a resume error. The output contains a hash manifest, module,
static guest PID-1 controller and initramfs. This command never boots, loads a
module or changes the host. Boot that initramfs only in a disposable QEMU guest
using the matching kernel; on this ARM64 lab machine the runs use EFI/KVM.

Require `PM_NOTIFIER_VM_RESULT ... result=0`, all `PM_OWNER_MODEL` records to
retain `debug_locks=1`, and the final record to have `held=0 task=0 refs=0`.
The prepare/thread/late cases must abort PM; the resume error must return
`NOTIFY_BAD` from POST even though the PM core ignores that return for its
sysfs result. Inspect serial logs, not just the sysfs write status. Collect
logs and bound guest lifetime externally (90 seconds used in the lab).

On 14 November all five final worker cases passed on the exact kernel33 Image.
The unpatched retained-writer model reproduced the circular dependency; its
scoped-lock control left Lockdep enabled. These are hardware-free regression
results, not native NVIDIA suspend/resume qualification.
