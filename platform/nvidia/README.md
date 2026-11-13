# NVIDIA DRM master-drop fix

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
