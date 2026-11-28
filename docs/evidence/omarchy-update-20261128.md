# Omarchy edge update on the P16

The starting point is the [qualified NVIDIA 620 default](nvidia620-native-20261127.md#default-boot)
on `@nvidia620-r3`. The 28 November edge transaction offers
`omarchy-dev 4.0.0.r8517.gf84b3bd-1` and the matching settings package,
Hyprland 0.57.2, PipeWire 1.6.12, systemd 262.2 and updated Limine tools.
[Omarchy revision](https://github.com/omacom/omarchy/commit/f84b3bd).

The update is staged on `@nvidia620-omarchy-20261128`, a separate writable
clone. The installed kernel38, thirteen P16/NVIDIA modules, NVIDIA 620.70.06
userspace, Tegra RMAPI package, NVENC correction and VT sleep handoff form
the retained hardware stack. The clone's Pacman configuration holds
`nvidia-open-dkms`, `nvidia-utils` and `opencl-nvidia` so an ordinary
update cannot replace a component of the version-bound setup. The existing
OpenCL package stays at 615.78.08 and is outside this qualification.
NVIDIA 620.73.04 needs a matched rebuild and a separate qualification.
[GB20B suspend report on 620.73.04](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1577).

The staged Pacman run uses the signed edge and Arch Linux ARM repositories.
The live EFI partition is absent from the clone during the transaction.
Boot and DKMS hooks are deferred while the qualified module bundle is
retained. The P16 pre-transaction guard and Omarchy's sudo-grant revocation
remain in effect. A private `/run` supplies DNS and the runtime directories
needed by package hooks. The initial attempts stopped before any package
change while those directories were being set up.

The 350-package transaction completed in the clone. The P16 preflight passed,
all kernel38 DKMS module bytes matched the running root, and the existing
EFI applications retained their hashes. Omarchy's N1x detection identified
the laptop as `aarch64-n1x`. Its firmware filter now omits Turing GSP
files from the updated UKI and keeps the GB20B firmware. The candidate retains
Plymouth and the P16 panel-brightness hook for disk unlock. It retains SDDM
with its greeter configuration and theme copied from the qualified system.
The systemd-boot restore hook is excluded from this Limine image. The broader
Omarchy migrations, including the new greeter and splash, have not been run
against the shared home.

The new packages carry libplacebo 7.387.0 and sndio 1.11.0. The existing
`ffmpeg-n1x` binary links to libplacebo ABI 360 and sndio ABI 7. Two local
compatibility packages carry only the qualified versioned runtime files
`libplacebo.so.360` and `libsndio.so.7`. The updated packages own their
original development symlinks and new runtimes. Both compatibility files
match the previous installation byte for byte.

Hyprland 0.57.2 reported `config ok` against a temporary copy of the user's
configuration. The isolated parser reported an IPC socket warning while no
desktop session was started. From the updated root, `nvidia-smi` found the
running RTX Spark on 620.70.06. `p16-nvenc-run ffmpeg-n1x` encoded ten
frames of H.264, HEVC and AV1 each. The updated system FFmpeg identified
the correct codecs and independently decoded all thirty frames.

## Staged boot

Select **P16 Omarchy Update 620** in the normal Limine menu. It boots
`@nvidia620-omarchy-20261128` (Btrfs ID 271). The new UKI lives at
`/boot/EFI/Linux/p16_nvidia620_omarchy_20261128.efi`, with SHA-256
`e36c19cf5f27ef1c6061a33ea5234dcee503305ec27b13e96e5176c31bcedc53`.
It retains `nvidia.p16_s2idle=1` and the DSP command line. Platform
verification checked 8,504 installed and 430 embedded modules with BTF,
the legacy ACPI profile, the kernel payload and the SPI HID modules.
The four embedded NVIDIA modules matched their installed bytes.

Limine validated all entry hashes and read back the published menu.
The existing `P16 NVIDIA 620 DRM + Suspend Test` default, recovery
entries, original EFI binaries and firmware order were preserved.
The previous menu is at
`/boot/limine.conf.before-omarchy-20261128-20261128T100632Z`.
The EFI partition has approximately 96 MiB free after staging.

Local receipts, package recipes and the boot-specific qualification wrapper
are under `build/omarchy-update-20261128/`. On the first candidate boot,
verify the graphical login and then run `qualify/qualify pre` for the
same display, media and audio checks used on the current default. The
wrapper requires the exact updated Omarchy build and both patched loaded
modules. Use a single attended s2idle cycle to check the updated systemd
and PipeWire path with the retained kernel. Native boot, physical resume
and promotion to default remain pending.
