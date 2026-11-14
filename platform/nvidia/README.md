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

For subsequent DKMS builds with the same vendor version:

```sh
cd platform/nvidia
makepkg --cleanbuild
pkexec --disable-internal-agent /usr/bin/pacman -U ./n1x-nvidia-drm-fix-615.78.08-2-any.pkg.tar.*
```

This small package installs the standard DKMS `PATCH[0]` configuration for
**615.78.08 only**, with the patch in `/etc/dkms/nvidia/patches/`. It preserves
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

The candidate-module builder applies both patches to its private NVIDIA copy
and pins both modified source files. All five candidate NVIDIA modules built
against kernel33 and passed split-BTF validation against its exact vmlinux.
The unchanged vendor core objects were reused only after verifying all 3,535
core source input hashes against the earlier kernel33 bundle. The installed DKMS patch package above
still includes **only the previously qualified DRM fix**; it does not deploy
this PM candidate. Native verification of the new NVIDIA modules, device-only
PM with clean Lockdep, and then real s2idle remain required. Do not unload the
active desktop GPU or reset Lockdep to substitute for that qualification.
