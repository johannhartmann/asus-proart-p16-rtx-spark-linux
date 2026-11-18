# NVIDIA 620 test package for the N1X

This recipe packages the repository's DRM colorspace, PM notifier and UVM PM
lock-order patches for the ARM64 distribution's
`nvidia-open-dkms 620.70.06`. It installs a version-scoped
`/etc/dkms/nvidia-620.70.06.conf`, so DKMS applies the three patches without
editing vendor source in place. The patch files are symlinks to the shared
source files in `platform/nvidia/` and were applied with fuzz zero to both
the official `.run` source and the signed distribution DKMS source.

Build with `makepkg --verifysource` and `makepkg --nodeps`; `--nodeps` is only
for offline packaging while the normal root still uses NVIDIA 615.78.08.
The resulting package conflicts with the 615 fix package and belongs only in
an isolated 620 test root with matching `nvidia-utils` and DKMS packages.
The prebuilt 620 platform module bundle is separate; see the
[offline receipt](../../../docs/evidence/n1x-media-20261118/nvenc-620-kernel38-offline.json).
No native 620 display, NVENC or suspend result is implied by this recipe.
