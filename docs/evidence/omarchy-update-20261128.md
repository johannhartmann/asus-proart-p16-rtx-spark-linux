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
wake.

### First native boot

The laptop booted the new kernel and the updated Btrfs root on 28 November.
Hyprland drove the internal panel at 3840×2400 at 120 Hz and the attached
DisplayPort screen at 3840×2160 at 30 Hz. Both internal panel DPMS cycles
completed. NVENC and NVDEC each processed ten frames of H.264, HEVC and AV1.
Both integrated cameras delivered all thirty frames. The speaker and
microphone advanced their hardware PCM pointers, all three DSPs reported
ASoC ready, and the sensor and SPBM register reads succeeded. The wrapper
now resolves the `/lib` symlink before checking module ownership paths.

The kernel reported a lock ordering cycle during USB4 hub enumeration.
`usb_acpi_find_companion()` attempts a device link while the ACPI lookup
holds `bus_type_sem`, and the WMI probe recorded the opposite dependency
through `device_links_lock` and `dpm_list_mtx`. Lockdep subsequently
reported `debug_locks=0`. The attended s2idle run is pending with working
Lockdep. The startup and peripheral results above are from this boot.

### Omarchy migration interrupted by EFI capacity

Omarchy's migration `1794673542` invokes a rebuild of all installed
kernels. The 2 GiB EFI partition ran out of space during the atomic copies
of the kernel38 and Omarchy P16 UKIs. The running candidate's legacy
command line also still used `quiet loglevel=0 systemd.show_status=false`,
with deferred framebuffer takeover. The journal and `/var/log/boot.log`
contain the boot records.

Before repairing the migration, the boot images and menu were copied and
verified under `build/omarchy-kernel-7.3.6/migration-repair/archive-20261128T115147Z/`.
The package state was archived in the read-only Btrfs subvolume
`@nvidia620-omarchy-before-migration-repair-20261128T115147Z`.
Kernel34 and kernel36 images moved to the archive. The obsolete kernel34,
kernel36, kernel37 and unused stock Omarchy kernel packages were retired
from the test root's package database. The explicit firmware entry for
kernel37 still has its image. The EFI filesystem then had 580 MiB free.

The managed Limine entry **Omarchy → linux-p16-platform-omarchy** now
points at `/boot/EFI/Linux/omarchy_linux-p16-platform-omarchy.efi`.
Its package-specific command line selects the updated snapshot and retains
the DSP and NVIDIA suspend parameters. `fbcon=nodefer`, `loglevel=7` and
`systemd.show_status=yes` enable the text console and boot messages. The
UKI embeds the Omarchy logo and the initramfs contains the current
Omarchy splash with its German unlock keymap and N1X backlight hook.
The local early-boot hook sets `SWAY_UNSUPPORTED_GPU=true` for the splash's
pixman renderer on early NVIDIA KMS.
[Sway GPU check](https://github.com/swaywm/sway/blob/1.12/sway/main.c),
[systemd-stub splash section](https://www.freedesktop.org/software/systemd/man/latest/systemd-stub.html).

The managed build, UKI payload, ACPI profile, module resolution, DSP
command line, and Limine menu hashes passed verification. The first managed
image hash was `eb6c92174945554767e1237d0d4e584a0601ea7980193500772aa8bcb7ae5589`.
The ESP had 361 MiB free. Trial builds of the two remaining older managed
images measured 146 MiB for kernel23 and 265 MiB for kernel38. The original
native candidate, qualified kernel38 entry and dedicated recovery image
retained their recorded hashes during this build. The updated graphical
unlock and visible boot console await a native boot.

The clone initially had an empty `/.snapshots` directory because nested
Btrfs subvolumes are outside a parent snapshot. A dedicated `/.snapshots`
subvolume was created within the upgraded root. `snapper -c root list` and
number cleanup both succeeded. The same live boot returned Pluton ABI 1
and passed two numerical cuDLA tests with 3,136 output bytes per case
matching the independent references.

The official `omarchy-migrate` runner resumed at `1794673542` and completed
all 101 pending migrations with exit status zero. Pacman reported a
consistent local package database, and the EFI filesystem had 305 MiB
free after the final rebuild. The Omarchy login migration enabled
`greetd.service` and disabled SDDM for the next start. The migration log is
`build/omarchy-kernel-7.3.6/migration-repair/migration.log`.
The final image matched the first managed build hash. Both managed kernel
images passed the P16 package guard. Limine also verified the standard
kernel38 entry, the dedicated recovery entry and all listed image hashes.

### USB4 power-management lock ordering

The native failure records `device_links_lock → dpm_list_mtx → bus_type_sem`
from WMI registration. USB4 enumeration recorded the reverse dependency by
adding a PM link from inside the protected ACPI companion callback. The
ACPI semaphore also protects callback lifetime during module unload.
[Upstream ACPI lookup change](https://lists.openwall.net/linux-kernel/2026/09/10/2532).

The [USB4 patch](../../ports/omarchy-7.3.6/usb4-pm-link-outside-acpi-lookup.patch)
moves link creation into `usb_new_device()`, after successful device and
port registration and before release of the enumeration runtime PM
reference. The root hub and non-tunneled devices skip the link. The
hotplug caller runs on the freezable USB hub workqueue. The original
stateless, runtime PM and active-supplier flags and disconnect cleanup
are preserved. No link is created on a registration error.
[Kernel device-link rules](https://docs.kernel.org/driver-api/device_link.html).

The resulting release is `7.3.6-10.1-omarchy-p16`. Its `Module.symvers`
matched the preceding build. The helper passed a mocked C test covering
tunnel eligibility, absent firmware suppliers, and link allocation
failure. Both ARM64 KVM boots kept `debug_locks=1` and produced zero
warnings. The second also enumerated a USB keyboard through emulated
xHCI. The ten external modules passed split BTF validation against the
new kernel. The raw image SHA-256 is
`5fb28a97ec90a873a3e06be536ea2c020570a62cfefae469eeb209c36d1a51c9`.

The three `7.3.6-10.1` packages are installed in the separate snapshot
`@nvidia620-omarchy-usb4-20261128` (Btrfs ID 274). The normal Limine entry
**Omarchy → linux-p16-platform-omarchy** selects this root and kernel.
The managed UKI SHA-256 is
`9afb452dd3db6c6a88e716ff989435a337d56161a0a8f1c0ffaa07038d43b25f`.
The package guard checked 8,524 installed and 427 embedded modules. The
NVIDIA module hashes, graphical unlock payload, boot logo, DSP options,
visible console configuration, and Limine entry hashes also passed.
The preceding managed image and menu are saved under
`build/omarchy-kernel-7.3.6/usb4-lockdep/boot-before-usb4-20261128T122346Z/`.
`P16 NVIDIA 620 DRM + Suspend Test` is the qualified default and
`P16 Omarchy Update 7.3.6` provides the previous Omarchy snapshot.

Native qualification uses one start of **Omarchy → linux-p16-platform-omarchy**.
Keep the USB4 dock and its external monitor attached during startup and
observe the boot splash, graphical disk unlock, console messages and login.
On this host, the staged qualification wrapper is
`build/omarchy-kernel-7.3.6/usb4-lockdep/qualify/qualify`. Its phases run
in this order, under the same kernel boot ID.

1. Run `qualify pre` in the desktop session. It verifies the release,
   root snapshot, loaded module versions, kernel journal, dock runtime
   PM link, internal panel DPMS, audio, RGB and IR cameras, NVENC and
   NVDEC for H.264, HEVC and AV1, and platform driver checks.
2. Run `qualify hotplug` and follow the unplug and replug prompts. The
   wrapper requires the USB4 link and an active external monitor to
   disappear, then the link and the same monitor to return. It records
   the transition and checks the corresponding kernel journal.
3. Run `qualify suspend` with graphical authorization when the user is
   ready to wake the laptop. Both earlier phases must have passed in
   this boot, and Lockdep must be active. The wrapper checks Pluton and
   NPU execution and records one physical s2idle attempt. After resume
   it checks the desktop VT, internal and external displays, the USB4
   link, media, audio, platform devices, both NPU vectors and Lockdep.

The wrapper never requests a reboot. A marker created before the
suspend request prevents a second automated attempt for the same boot.
Preflight or hotplug failures leave diagnostic logs under the boot ID
for investigation in the same session. The release guard was verified
on the preceding running kernel. Simulated sysfs, monitor and journal
data verified the hotplug transition, external monitor identity, the
Lockdep failure gate and the single-attempt guard before reboot.
