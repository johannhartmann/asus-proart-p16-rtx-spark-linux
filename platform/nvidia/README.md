# NVIDIA kernel fixes

## DRM master-drop recovery

NVIDIA 615.78.08's `nv_drm_reset_input_colorspace()` returns directly after
`drm_atomic_get_plane_state()` or `drm_atomic_commit()` reports `-EDEADLK`.
Dropping its locks with an unresolved contended lock triggers a kernel warning
and skips the intended colorspace reset. This occurred when logind dropped DRM
master during device-only PM on this P16. It is a separate display-driver issue
from DSP SRAM ownership and firmware resume.

The patch follows the [DRM locking contract](https://docs.kernel.org/gpu/drm-kms.html#kms-locking):
clear partial atomic state, back off the contended lock, then rebuild the
transaction. Backoff interruption is propagated and all resources are released.
`python3 platform/nvidia/test_deadlock.py` compiles the actual original and
patched function under AddressSanitizer/UBSan and injects plane and commit
deadlocks, interrupted backoff, changed plane state and terminal errors.

The candidate-module builder applies the patch to its private NVIDIA copy and
records the resulting source hashes. It never reloads the active desktop GPU.
Hardware qualification requires booting the matching bundle and checking DRM
master transitions and suspend/resume without the earlier warning.

For subsequent DKMS builds with the same vendor version, package revision 4 carries all three corrections. It is activated on the
qualified kernel36 workstation. Install it after the matching native
qualification on a new system:

```sh
cd platform/nvidia
makepkg --cleanbuild
pkexec --disable-internal-agent /usr/bin/pacman -U ./n1x-nvidia-drm-fix-615.78.08-4-any.pkg.tar.*
```

This small package installs standard DKMS `PATCH[0]` (DRM), `PATCH[1]` (PM owner)
and `PATCH[2]` (UVM lock order) configuration for **615.78.08 only**, with the patch files in `/etc/dkms/nvidia/patches/`. It preserves
the pristine vendor source under `/usr/src`. Installing the configuration does
not change a loaded module or by itself rebuild existing modules. Use the
complete candidate workflow for the next boot; do not unload NVIDIA from a
running desktop. Review the patch and update its version binding before moving
to a different NVIDIA source release.

## PM notifier lock ownership candidate

Native kernel33 device-only PM returned successfully on 14 November, but
Lockdep reported a cycle through `(pm_chain_head).rwsem`, `nv_system_pm_lock`,
`nvkms_pm_lock` and UVM's global PM semaphore. NVIDIA retains those writers
between PREPARE and POST; POST reacquires the notifier-chain reader in the
same task. A QEMU-only one-gate model reproduces that pattern without NVIDIA
hardware. This identifies a lock-order defect; the native run did not actually
deadlock, and the model does not prove that it caused earlier physical hangs.

`nvidia-pm-notifier-owner.patch` keeps the suspend and resume operations in one
dedicated, non-freezable kernel thread. The notifier waits for preparation;
POST joins the same thread after requesting resume. The gates remain closed
throughout the cycle and retain their real owner. No Lockdep annotations are
disabled, locks made untracked or gates released early. A module reference
spans the cycle; preparation/thread failures release it, and module exit
unregisters the notifier before tearing down resources.

The [QEMU integration fixture](../tests/pm-notifier-lock/README.md) compiles the
actual patched notifier with a hardware-free gate. Its normal, prepare-error,
thread-creation-error, later-notifier-abort and resume-error cases pass with
Lockdep active and no retained worker, gate or module reference.

The candidate-module builder applies all three patches to its private NVIDIA copy
and pins all four modified source files. Native kernel34 device-only PM passed
with the owner correction and Lockdep still enabled at its completion. A later
NVIDIA/I2C/platform-bus classification warning disabled that boot's validator;
see the separate per-bus lock-class fix in the
[suspend candidate](../../docs/suspend-candidate.md).

Kernel36 initially stopped on a further UVM inversion; the
[16 November record](../../docs/evidence/kernel36-native-20261116.json) preserves
that failure. With the UVM correction, the
[17 November native sequence](../../docs/evidence/kernel36-native-20261117.json)
passed physical sleep, audio/NPU operation after resume and two device-only
cycles with retained CUDA allocations. Four UVM callback returns were successful
and Lockdep remained enabled. The normal default now selects kernel36.

The installed global package is **revision 4**, carrying all three fixes. The
candidate builder includes those same patches. Installing their configuration
preserves loaded modules; future DKMS builds use the version-scoped corrections.
Do not unload an active desktop GPU, reset Lockdep or mix different kernel/BTF
sets to substitute for qualification.

## UVM PM collection and resume lock order

NVIDIA 615.78.08 retains each VA-space writer across suspend/resume. Resume
then reacquires the global VA-list mutex while those inner locks remain held,
reversing the normal list-to-VA order. Kernel36's native device-only test
reported that exact cycle with the existing same-task PM worker.

`nvidia-uvm-pm-lock-order.patch` uses the already-held global PM writer to
stabilize resume's VA-list traversal, avoiding that second list-mutex
acquisition. Every VA creation/destruction path takes a PM reader, so the writer
also pins their lifetimes. The PM-specific VA lock helper uses Linux nesting
primitives under that real outer writer for multiple same-class VA objects.
It retains all VA locks through sleep and leaves Linux Lockdep enabled.
NVIDIA's own cross-callback tracking was already disabled by the vendor code;
this patch does not expand that disabled interval.

The [UVM regression](../tests/uvm-pm-lock/README.md) extracts the real pinned
callbacks and lock helpers. Nine fresh EFI/KVM cases cover zero, one, two and
eight VA spaces, a blocked PM-reader/list mutator, four fixed suspend/resume
cycles, GPU callback state and deferred-release ordering. The original code
warns; the fixed code stays clean; a deliberate VA-to-list inversion still
warns. These are hardware-free lock regressions, not physical suspend proof.
The rebuilt UVM module targets the unchanged kernel36 Image and BTF.

The [native retained-context test](../tests/cuda-pm/README.md) verifies managed
buffer contents around device-only PM. Its completion collector initially
rejected a legitimate active desktop audio client; the follow-up final-state
check retained all fault and Lockdep checks while allowing that client. See
the native record for the exact test boundaries and collector outcomes.
