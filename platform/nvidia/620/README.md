# NVIDIA 620 test package for the N1X

This recipe packages the repository's DRM colorspace, PM notifier and UVM PM
lock-order patches for the ARM64 distribution's
`nvidia-open-dkms 620.70.06`. It installs a version-scoped
`/etc/dkms/nvidia-620.70.06.conf`, so DKMS applies the patches without
editing vendor source in place. The patch files are symlinks to the shared
source files in `platform/nvidia/` for the three shared corrections.
Those patches applied with fuzz zero to both the official `.run` source
and the signed distribution DKMS source.

Release 2 adds a retry for content protection work when an atomic display
commit already owns the connection lock. The first DPMS test reproduced
the lock cycle on the internal panel with the original module. The new
module builds against kernel38 and awaits native qualification.
[Trace and build record](../../../docs/evidence/nvidia620-native-20261127.md#drm-flip-timeout-on-the-internal-panel).

Release 3 adds an opt-in for s2idle on the ASUS ProArt P16 H7607BA with
GB20B `10de:2e03` and subsystem `1043:1484`. The option defaults off.
Use `nvidia.p16_s2idle=1` for the candidate boot with kernel suspend
notifiers and the existing systemd VT handoff and s2idle configuration.
Verify `/sys/module/nvidia/parameters/p16_s2idle` reports `Y`. Preserve a
known-working boot entry for recovery. The normal NVIDIA suspend and resume
sequence still runs when the GPU passes both admission checks. Native
suspend qualification of release 3 is pending.
[Suspend examination and qualification steps](../../../docs/evidence/nvidia620-native-20261127.md#gb20b-s2idle-candidate).

Build with `makepkg --verifysource` and `makepkg`. For offline packaging
without the matching host dependency installed, use `makepkg --nodeps`.
The package conflicts with the 615 fix package and requires a 620 root
with matching `nvidia-utils` and DKMS packages.
The prebuilt 620 platform module bundle is separate; see the
[offline receipt](../../../docs/evidence/n1x-media-20261118/nvenc-620-kernel38-offline.json).
The separate [NVENC session correction](nvenc/PKGBUILD) provides
`p16-nvenc-run` for the affected 620.70.06 userspace build. Its native
acceptance covers H.264, HEVC and AV1 in FFmpeg.
[NVENC session and encoding checks](../../../docs/evidence/nvidia620-native-20261127.md#nvenc-session-handle-correction-on-6207006).
