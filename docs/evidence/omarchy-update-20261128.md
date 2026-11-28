# Omarchy edge update on the P16

The starting point is the [qualified NVIDIA 620 default](nvidia620-native-20261127.md#default-boot)
on `@nvidia620-r3`. The 28 November edge transaction offers
`omarchy-dev 4.0.0.r8517.gf84b3bd-1` and the matching settings package,
Hyprland 0.57.2, PipeWire 1.6.12, systemd 262.2 and updated Limine tools.
[Omarchy revision](https://github.com/omacom/omarchy/commit/f84b3bd).

The update is staged on `@nvidia620-omarchy-20261128`, a separate writable
clone. The initial desktop update used kernel38 and its thirteen P16/NVIDIA
modules. The clone retains NVIDIA 620.70.06 userspace, the Tegra RMAPI
package, the NVENC correction and the VT sleep handoff. Its Pacman
configuration holds
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

## Initial desktop-only image

The first UKI used kernel38 and was registered as **P16 Omarchy Update 620**
for `@nvidia620-omarchy-20261128` (Btrfs ID 271). It was staged at
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

Local receipts and package recipes are under `build/omarchy-update-20261128/`.

## Omarchy Linux 7.3.6 with the P16 port

The [P16 port](../../ports/omarchy-7.3.6/README.md) uses the exact ARM64
`linux-omarchy 7.3.6-10` package revision. The reconstruction verified the
recipe against the published package build record, matched the signed
headers configuration, verified the Linux 7.3.6 source signature and
applied Omarchy's 616 kernel patches. Of the nineteen kernel38 changes
reviewed, sixteen carried over directly, two needed a rebase, and the IPv4
RCU change was already present. The build retains Lockdep and DMA API
checking for native qualification.

The new kernel supplies MT8901 pinctrl, SSPM CI, ARM SMMUv3, SPI-HID and the
ambient light sensor. The P16 overlay adds the AFE SRAM and SoundWire
fixes, ASUS WMI and battery support, the ACPI and translated DMA fixes,
camera buffer constraints, and PCIe and SDHCI resume corrections.
The DSP, NPU/SROOT, Pluton, SCP and SPBM modules each have a build for the
new ABI. The five NVIDIA modules keep the 620.70.06 P16 fixes and add all
seven Omarchy display patches, including the OLED and USB-C DisplayPort
changes. Release-specific DKMS overrides keep the same patch selection and
the in-tree sensor modules on future rebuilds of this release.

The independently prepared source tree reproduced the configuration and
patched files. The 37 targeted regression tests covered AFE, driver PM,
translated DMA, NVIDIA DRM, SPI-HID, the light sensor, module BTF and Pluton.
An ARM64 KVM boot of the resulting `Image` reported
`7.3.6-10-omarchy-p16`, `debug_locks=1` and zero warnings. The raw image
SHA-256 is `c8d7d7d247c5e3c49181c47a558e2ecdcf6ef1b40d3cb24a2072a2f3553e4789`.

The ten external modules passed BTF validation against the new kernel.
The extracted headers package was also used to rebuild `n1x_scp.ko` and
validate its ABI and BTF. The split packages are ARM64 version `7.3.6-10`.

| Package | SHA-256 |
| --- | --- |
| `linux-p16-platform-omarchy` | `642c33125a887d5cae2e26e3d95254804f69bd205a47a05e0a8273e33f63fea7` |
| `linux-p16-platform-omarchy-headers` | `1d8839bffe8261d78b92c5ba377fc8985a8718a711a8ec9a538aeba376526951` |
| `linux-p16-platform-omarchy-drivers-nvidia620` | `513656c2486d8bff6803f8cf7ee343e2bf0e0d3c8473198fcf711c5e8ff883c4` |

### Staged boot and native qualification

Select **P16 Omarchy Update 7.3.6** in the normal Limine menu. This entry
boots the updated snapshot `@nvidia620-omarchy-20261128` (Btrfs ID 271) with
kernel `7.3.6-10-omarchy-p16` and NVIDIA `620.70.06`. Its UKI is
`/boot/EFI/Linux/p16_omarchy_7.3.6_620.efi`, SHA-256
`1f77c03a82eb396b0897b67b248586c591a6d4227c4db5d1eeb49b19a689c014`.
Limine verified the candidate entry hash, the current default **P16 NVIDIA
620 DRM + Suspend Test** and **Omarchy-P16-Recovery**. The firmware boot
order and all other EFI hashes matched the pre-staging readout. The prior
desktop-only UKI was archived under `build/omarchy-kernel-7.3.6/` and the
previous menu was saved as
`/boot/limine.conf.before-omarchy-7.3.6-20261128T110240Z`.

Pacman found zero altered files in each of the three installed packages.
The published image passed checks for the exact kernel payload, legacy
ACPI profile, matching SPI-HID modules, DSP root and command-line options,
and split BTF for 8,524 installed and 427 embedded modules. All four
embedded NVIDIA modules matched the installed bytes. The initramfs builder
reported the same Renesas firmware and ARM64 microcode-hook warnings as
the initial desktop-only image.

The local wrapper is `build/omarchy-kernel-7.3.6/qualify/qualify` on the
shared home subvolume. After disk unlock and login, `qualify pre` checks
the exact kernel and module identities, panel DPMS, external connector
state, RGB/IR capture, speaker and microphone, the ambient light sensor,
and H.264, HEVC and AV1 via NVENC and NVDEC. With the USB-C hub connected,
confirm that the external display lights and record the connector state
before and after a replug. After a passing preflight and an attended wake
is ready, `qualify suspend` checks the Pluton diagnostic interface and
cuDLA, requests one s2idle cycle, and repeats the device checks after
wake. Native startup, external display and physical resume are pending.
