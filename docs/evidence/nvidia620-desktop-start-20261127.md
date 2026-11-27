# First native NVIDIA 620 start on the P16

The `P16 NVIDIA 620 Test` Limine entry started kernel
`7.2.8-38-rtx-spark-npu` with `rootflags=subvol=@nvidia620` on 27 November.
The journal for boot `4e9432d8dbe14263abce4004aa75e91f` records the
620.70.06 NVIDIA and modeset modules loading, DRM registering a framebuffer,
and systemd reaching the graphical target at 07:49:23 CET. All three N1X
audio DSPs reported firmware ready. These observations establish startup
through root mount and driver initialization.

Hyprland then aborted in `CHyprOpenGLImpl::initEGL`. Its crash report and
the journal show `EGL_NOT_INITIALIZED` and Mesa DRI2 screen creation
failures on NVIDIA PCI device `10de:2e03`. Hyprland also aborted when
started for the SDDM greeter, which then failed to initialize Qt Wayland.
The kernel journal continued after both crashes. The user returned to
the standard Kernel36/NVIDIA 615 system.

## Missing NVIDIA ARM64 library

With `@nvidia620` mounted read-only, the candidate's AArch64 dynamic
loader could not resolve `libnvidia-rmapi-tegra.so.620.70.06` when
listing the dependencies of `libEGL_nvidia.so.0` or
`libnvidia-eglcore.so.620.70.06`. The signed Arch Linux ARM
`nvidia-utils 620.70.06-1` archive omits this file. The installed GBM
backend link, NVIDIA EGL vendor manifest and upstream GBM plugin were
present. Pacman package-integrity checks alone missed the omission
because they check files declared in the archive.

The [local package recipe](../../platform/nvidia/620/rmapi-tegra/PKGBUILD)
extracts the exact ARM64 library from the [NVIDIA 620.70.06 installer](https://www.nvidia.com/en-us/drivers/details/283904/).
The installer SHA-256 is
`3fa65a9271e0dde2a4e58c4965c38885a02a3a42accdcb26fc817410607f3e03`.
The library SHA-256 is
`10e890c6ad8d76c02f4f957d4867b0c61be80a9400302934e5e424fd5d7f8643`.
The build verifies the vendor archive and extracts files without running
the driver installer. No proprietary binary is committed to the repository.

Build from the recipe directory with `makepkg --nodeps`. This skips the
build host's runtime dependency check because that host runs NVIDIA 615.
Pacman still enforces the exact 620 dependency when installing the package
in the candidate.

The [candidate repair helper](../../scripts/install-nvidia620-egl-repair)
installs the version-locked package in `@nvidia620` and checks the ELF
dependencies of the graphics, CUDA, NVML, NVENC and NVDEC entry points
with the candidate's own dynamic loader. Launch it in a private mount
namespace from the 615 system:

```sh
pkexec --disable-internal-agent /usr/bin/unshare --mount --propagation private \
  /absolute/path/to/scripts/install-nvidia620-egl-repair \
  /absolute/path/to/p16-nvidia620-rmapi-tegra-620.70.06-1-aarch64.pkg.tar.xz
```

The repair was installed into `@nvidia620`. `pacman -Qkk` found all
seven entries intact and the candidate dynamic loader resolved all nine
checked libraries successfully. The EFI and Limine staging paths now
run the same check. The existing UKI requires no rebuild for this
userspace package. Native display startup, codec calls, audio playback
and suspend still require qualification after repair.
