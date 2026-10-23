# Linux support for the ASUS ProArt P16 RTX Spark

Kernel patches, driver setup and a reproducible installation guide for running
**Omarchy Linux ARM64 on the ASUS ProArt P16 H7607BA**, powered by the
**NVIDIA RTX Spark N1X** platform.

This repository supplies the machine-specific fixes needed to turn an Omarchy
ARM64 Nightly installation into the P16 setup used on the validated hardware.
It covers internal input, ACPI and battery reporting, ASUS controls, NVIDIA
graphics configuration, USB4 boot settings and power/temperature telemetry.
The guide below takes you from the Nightly installation through building,
installing and checking the patched kernel, with recovery instructions.

## What this repository provides

| Area | Included support |
|---|---|
| Internal keyboard and touchpad | ACPI/SSPM enumeration fixes, early input modules and keyboard support at the encrypted-disk prompt |
| Kernel and firmware interfaces | A separately packaged P16 kernel, ARM64 ACPI override allocation fix, firmware-table transformations and SPI-HID fixes |
| ASUS controls | ARM64 WMI support, power-profile integration and a battery charge-limit service |
| NVIDIA graphics | NVIDIA open DKMS setup, early module loading, DRM modesetting/fbdev and a block on the conflicting legacy `nvidiafb` driver |
| USB4 and boot configuration | Explicit USB4 resource retention, PCI hotplug reservations, suspend-to-idle selection and the SimpleDRM workaround |
| Power and temperature monitoring | A temperature CLI and the pinned [RTX Spark `spark_hwmon` driver](https://github.com/johannhartmann/spark_hwmon/tree/rtx-spark), with 15 power readings, eight temperatures and four reduction-only power-limit controls on the validated firmware |
| CUDA | Toolkit installation, an `sm_121` GPU verification program and NVIDIA container setup instructions |
| Installation and recovery | Checked source inputs, a separate kernel/UKI, configuration and EFI backups, Limine hash verification and rollback tools |

The kernel recipe and P16 patches are included here. The `spark_hwmon` source,
installer and tests are fetched at an immutable commit by
`scripts/prepare-spark-hwmon.sh`; `sources.json` records the upstream source pins.
ACPI overrides are generated from the target machine's own firmware tables.

## Supported hardware and software

| Component | Validated target |
|---|---|
| Laptop | **ASUS ProArt P16 H7607BA** |
| Platform / GPU | **NVIDIA RTX Spark N1X**, AArch64, GPU `10de:2e03`, CUDA compute capability **12.1** |
| Firmware | BIOS **H7607BA.300**, EC **2.16** |
| Base installation | Official **Omarchy ARM64 Nightly** |
| Patched kernel | Omarchy recipe **7.2.8-23**, producing **7.2.8-23-omarchy-p16-asus** |
| Validated NVIDIA driver | **615.78.08**, open kernel modules |

The install scripts check the laptop model and BIOS. The ACPI builder checks
firmware-table hashes; the expanded `spark_hwmon` register backend has its own
model/BIOS checks. Other ProArt P16 variants, RTX Spark machines and firmware
versions require separate validation.

A newer Nightly may ship a newer stock kernel. This guide installs the pinned
P16 kernel alongside it and preserves the existing boot entries. Apply these
patches only to the pinned source; see [boot recovery and updates](#9-boot-recovery-and-updates)
for upgrades.

## Scope and remaining limitations

This is a hardware enablement and installation repository. Application choices,
desktop appearance and Python/model-training environments are configured
separately. Factory fan curves remain active; custom ASUS fan control is not
provided. Some sensor functions and suspend/hibernate scenarios still require
testing. Energy calibration, PROCHOT polarity and some `spark_hwmon` diagnostic
fields remain unresolved and are exposed only as raw data. See
[hardware and limitations](#hardware-and-limitations) for the remaining checks.

## Installation

## 1. Install the ARM64 Nightly

Clone this repository on the machine used to prepare the installation USB drive:

```bash
git clone https://github.com/johannhartmann/asus-proart-p16-rtx-spark-linux.git
cd asus-proart-p16-rtx-spark-linux
```

You need a USB drive of at least 8 GB, a USB keyboard for initial setup, AC power and internet access. Disable Secure Boot in UEFI. Selecting a full-disk installation erases the selected drive.

Download and verify the current ARM64 Nightly:

```bash
python3 scripts/download-nightly.py
```

The script reads the [ARM64 Nightly manifest](https://nightly.omarchy.org/edge-aarch64/latest.json), checks the architecture, file size and SHA-256, and saves the ISO and manifest under `build/iso/`. The separate `edge/latest.json` points to the x86_64 image.

Write the ISO to the USB drive using an image writer. Select the drive in the UEFI boot menu and install Omarchy. Choose your keyboard layout in the installer. The P16 kernel command line needs these parameters:

```text
console=tty0 acpi=nospcr acpi_osi="!Windows 2022"
```

`console=tty0 acpi=nospcr` is part of Omarchy's N1X configuration. On this BIOS, `acpi_osi="!Windows 2022"` enables SSPM/I²C enumeration needed by the internal keyboard and touchpad. Use the USB keyboard if internal input is unavailable in the installer. Step 5 embeds the required parameters in the P16 kernel's boot image.

After installation, boot the installed system into the regular Omarchy session. Make this repository available on that system and run the remaining commands from its root directory. Use `sudo` where shown.

## 2. Install build tools and platform packages

```bash
omarchy pkg add base-devel bc cpio gettext libelf pahole python git gnupg clang llvm lld rust rust-bindgen rust-src xxhash zstd
omarchy pkg add nvidia-open-dkms nvidia-utils python-gobject
```

The Nightly configures the N1X platform, NVIDIA graphics, encrypted boot and Limine. Use the NVIDIA packages from Omarchy's AArch64 repositories.

Install Omarchy's NVIDIA-aware power profile daemon:

```bash
sudo pacman -S --needed omarchy-power-profiles-daemon
sudo systemctl enable power-profiles-daemon.service
```

Confirm replacement of `power-profiles-daemon` if Pacman prompts for it. The Omarchy package provides the same service and `powerprofilesctl` command.

## 3. Generate the ACPI overrides

Dump the original firmware tables while running the stock Nightly kernel, **before booting a kernel with ACPI overrides**:

```bash
sudo ./scripts/dump-acpi.sh
python3 scripts/build-acpi.py
```

The build uses the included ACPICA **20260408** source and checks the original tables and both generated overrides against pinned SHA-256 hashes. It rejects other firmware tables and tables that have already been patched. The dump script creates the parent `build/` directory with ownership assigned to the user who will compile the sources. It refuses to overwrite an existing `build/firmware/` directory.

Outputs:

```text
build/acpi/kernel/firmware/acpi/DSDT.aml
build/acpi/kernel/firmware/acpi/SSDT.aml
build/acpi/manifest.json
```

The DSDT corrects SSPM enumeration; the SSDT corrects EC and battery methods. The kernel includes the ARM64 allocation fix required for these overrides. Load the tables through the included initramfs hook for the P16 kernel. This does not flash the BIOS.

## 4. Build the P16 kernel

Run as your regular user:

```bash
./scripts/build-kernel.sh
```

The first run downloads the Linux source. Signature verification remains enabled, using an isolated GPG directory under `build/gnupg/`. Allow several tens of GB of free disk space. The build produces:

```text
kernel/linux-p16-asus-23-7.2.8-23-aarch64.pkg.tar.zst
kernel/linux-p16-asus-23-headers-7.2.8-23-aarch64.pkg.tar.zst
```

NVIDIA-DKMS requires the headers package. Pacman owns the installed kernel and modules; the installed headers allow DKMS builds after the source build directory has been removed.

`kernel/PKGBUILD` specifies the patch order and SHA-256/BLAKE2 checksums. Omarchy already includes the SPI-HID transport series; the remaining P16 patches add the ACPI IRQ retry, virtual GPIOs, thermal filtering and ACPI allocation fix. The combined ASUS patch already includes ARM64 WMI support, relocation to `drivers/platform/asus/` and the P16 RSOC fix. Apply it once as part of the recipe.

## 5. Install the kernel and system configuration

The new package is named `linux-p16-asus-23` so an existing `linux-p16-asus` package and its `7.2.8-14-omarchy-p16-asus` kernel stay installed. Keep the old kernel and boot entry until the new kernel has booted successfully. The ACPI hook and ASUS services continue to support that older P16 kernel.

From the installed Omarchy system:

```bash
sudo ./scripts/install-kernel.sh
```

The installer:

- checks the architecture, model, BIOS, mounted EFI partition and ACPI files;
- backs up affected configuration files and complete existing EFI images, with checksums, under `/root/p16-install.XXXXXXXX/`;
- installs the kernel and headers, builds NVIDIA-DKMS and generates module dependencies;
- installs early input drivers, the kernel-specific ACPI hook and ASUS services;
- preserves the target machine's root/LUKS parameters and adds the validated P16 boot parameters;
- installs NVIDIA DRM modesetting/fbdev configuration and blocks the conflicting legacy `nvidiafb` driver;
- builds an additional unified kernel image (UKI) and verifies its kernel, ACPI tables and required modules;
- registers `linux-p16-asus-23` with Limine and verifies EFI BLAKE2b hashes;
- displays the boot menu for ten seconds while preserving the existing default entry.

The generated P16 UKI explicitly includes `power_wrap_drv.usb4_release=0`,
`pci=hpbussize=0x80,hpmmiosize=32M,hpmmioprefsize=32G`,
`mem_sleep_default=s2idle` and
`initcall_blacklist=simpledrm_platform_driver_init`, in addition to the console
and ACPI options above. These retain USB4 resources, reserve PCI hotplug space,
select suspend-to-idle and avoid the conflicting SimpleDRM initialization.
The corresponding Limine drop-ins preserve these options during later UKI
rebuilds. They apply to the normal default command line; keep Omarchy's separate
fallback command line for recovery. Existing `pci=` settings are replaced with
the validated P16 values; unrelated initcall blacklist entries are preserved.

NVIDIA `modeset=1` and `fbdev=1` are installed before the new initramfs is built.
Use the packaged Omarchy Hyprland NVIDIA defaults for the graphics environment.
With the validated NVIDIA 615.78.08 open driver, the packaged
`NVreg_UseKernelSuspendNotifiers=1` configuration handles suspend; do not add the
legacy NVIDIA suspend services alongside it. This is configuration coverage,
not a claim that every suspend or hibernation scenario has been tested.

Existing EFI images are preserved. The root filesystem needs enough space for their complete backup, in addition to the kernel build space. The installer locks the boot partition against concurrent Limine writes.

On an error or Ctrl+C, the installer restores the backed-up boot files and system configuration. Installed kernel/header packages remain in place. After resolving the error, resume using the same package files:

```bash
sudo ./scripts/install-kernel.sh --resume /root/p16-install.XXXXXXXX
```

Replace `XXXXXXXX` with the actual backup suffix printed when installation started. Resume validates the root-owned checkpoint, all backup files and both package checksums. It restores the original boot files before repeating installation. This also supports recovery from an interruption that prevented automatic restoration. A successfully completed installation cannot be resumed. Checkpoints created before the NVIDIA/platform configuration additions can still be restored, but must be resumed using their original installer revision. A manually restored checkpoint can be resumed with the same package files while the boot environment still matches.

Reboot and select **`linux-p16-asus-23`** in the Limine menu. Then check:

```bash
uname -r
./scripts/check-system.sh
sudo python3 scripts/verify-boot.py
```

`uname -r` must report `7.2.8-23-omarchy-p16-asus`. Battery readings should be plausible, `nvidia-smi` should list the GPU, and the three services should have started successfully. `powerprofilesctl list` should report `nvidia_rtx_spark` and `platform_profile` as drivers.

## 6. Configure a German keyboard layout

For a German layout, run these commands as your regular user in the graphical session:

```bash
python3 scripts/set-german-keyboard.py
sudo localectl --no-convert set-keymap de
sudo limine-mkinitcpio
sudo python3 scripts/verify-boot.py
```

The script sets the desktop and Fcitx to `de` using Omarchy's installed keyboard configuration logic, then reloads Hyprland. `localectl` sets the console keymap; rebuilding the UKIs embeds it for the LUKS prompt on the next boot. The `hid_asus` driver is included in the initramfs for internal keyboard input.

## 7. ASUS profiles, battery and temperatures

Select a power profile:

```bash
powerprofilesctl set balanced
powerprofilesctl set performance
powerprofilesctl set power-saver
```

Balanced maps to ASUS Balanced, Performance to ASUS Performance, and Power Saver to ASUS Quiet. The daemon also controls the NVIDIA CPU backend.

`p16-asus-controls.service` loads the ASUS driver before power profile discovery. `p16-charge-limit.service` sets the charge limit to **100%** after battery registration. Both services are restricted to the validated ASUS P16 kernel releases (`7.2.8-14` and `7.2.8-23`). The factory fan curves remain active.

Display temperatures:

```bash
p16-temperatures
p16-temperatures --watch
p16-temperatures --json
```

The monitor reads ACPI, NVIDIA, NVMe, Wi-Fi and fan interfaces. The kernel excludes PSYS/PSOC power telemetry from thermal zone registration. Eight firmware zones have invalid `_CRT` limits (`0x7fffffff`); their temperature readings work, but no replacement thresholds are introduced. THRM's existing 100 °C passive and 103 °C critical limits are preserved.

### RTX Spark power and temperature telemetry

After rebooting successfully into `7.2.8-23-omarchy-p16-asus`, install the
validated `spark_hwmon` backend. Its complete source and tests are fetched from
the immutable commit in `sources.json`, version **0.3.0.rtxspark.5**:

```bash
omarchy pkg add dkms
./scripts/prepare-spark-hwmon.sh
sudo ./build/spark_hwmon/scripts/install-dkms.sh
cat /sys/module/spbm/version
python3 build/spark_hwmon/tests/check-n1x.py --require-all --require-mmio
```

The installer requires headers for the running kernel, builds before replacing
the module, and restores the previous DKMS version if replacement fails. Its
ACPI aliases load `spbm` automatically on subsequent boots; no extra service is
needed. DKMS rebuilds it for future kernels with installed headers. This module
is installed separately from the kernel transaction; the kernel restore command
does not uninstall it.

On this model and BIOS it exposes 15 power readings, eight temperatures, four
reduction-only power-limit controls and raw status/energy/diagnostic words under
`/sys/class/hwmon/` (`name=spbm_n1x`). Installation does not change power limits.
Absolute energy calibration, PROCHOT polarity and some diagnostic meanings remain
unresolved; raw values must not be presented as calibrated energy or alarms.
See the fetched driver's README and validation reports before using controls.

## 8. CUDA and GPU containers

```bash
omarchy pkg add cuda
source /etc/profile
nvcc --version
./scripts/check-cuda.sh
```

The toolkit is installed under `/opt/cuda`. The test compiles for **`sm_121`** and verifies all 4096 results of a GPU vector addition. Success produces `"result":"passed"`. NVIDIA-SMI reports the driver's CUDA capability; `nvcc --version` reports the installed toolkit version. Prebuilt PyTorch wheels also have their own CUDA runtime version.

To enable GPU access in Docker:

```bash
omarchy install docker
omarchy pkg add nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
sudo systemctl restart docker
```

Start GPU containers with `docker run --gpus all ...`. Restarting Docker interrupts running containers. Python training environments and Kubernetes are separate from this hardware setup.

## 9. Boot recovery and updates

If the P16 kernel fails to boot, select the existing `linux-omarchy` entry in Limine. Use `linux-omarchy-fallback` if the display stays black. Press `Esc` to reveal a hidden boot menu. The stock kernel does not activate the P16 ACPI overrides or the two P16 services.

To restore the original configuration, boot the stock kernel and run:

```bash
sudo ./scripts/restore-install.sh /root/p16-install.XXXXXXXX
```

Use the actual backup suffix. The script validates all backups and compares the stock kernel images and installed Linux/NVIDIA package versions against the checkpoint before writing any files. Changed versions or missing compatibility metadata cause restoration to stop without changing the current boot files. For a matching environment, it restores the EFI images, matching Limine configuration, system files (including the original console keymap) and previous service enablement link. It removes newly created P16 boot files while leaving kernel/header packages installed. To install again after restoration, use `install-kernel.sh --resume` with that same checkpoint and unchanged package files.

For a BLAKE2b mismatch, restore the EFI image and its matching menu entry together. Do not modify an EFI image after registering its hash. Inspect PE sections with read-only tools. `scripts/verify-boot.py` does not modify images and rejects missing P16 entries as well as missing, malformed or incorrect hashes.

After an NVIDIA package update, ensure DKMS builds successfully for the P16 kernel:

```bash
dkms status
sudo dkms autoinstall -k 7.2.8-23-omarchy-p16-asus
sudo depmod -a 7.2.8-23-omarchy-p16-asus
```

Then rebuild the UKI through Omarchy's `limine-mkinitcpio` workflow and run `sudo python3 scripts/verify-boot.py` so the initramfs and root filesystem contain matching drivers. Preserve the stock kernel and its fallback entry when changing kernels.

After a BIOS update, do not boot the P16 kernel with the old ACPI overrides. Boot the stock kernel and use the restore command to remove the P16 setup. Restoration checks the model but allows a changed BIOS; installation continues to require H7607BA.300. If stock kernels or NVIDIA packages were also updated, the old backup cannot safely restore their boot files: keep the current stock images and repair from the stock kernel instead of copying old EFI files back. Supporting a different kernel release requires updating and checking the patches, mkinitcpio hook, drop-in and service `ConditionKernelVersion` settings together.

## Hardware and limitations

| Hardware | Identity |
|---|---|
| GPU | NVIDIA `10de:2e03`, subsystem `1043:1484`, compute capability 12.1 |
| Internal keyboard | HID `0b05:4b42`, ACPI `MKB0001`, `hid_asus` |
| Touchpad | HID `093a:4f01`, `hid-multitouch` |
| SPI sensor hub | `MSFW1111` / `PNP0C51`, virtual GPIO/IRQ 190, `spi_hid_acpi` |
| ASUS WMI | Management `97845ED0-4E6D-11DE-8A39-0800200C9A66`, event `0B3CBB35-E3C2-45ED-91C2-4C5A6D195D1C` |

SPI-HID provides the sensor hub transport. Complete sensor measurements, physical charge cutoff, fan response, suspend/resume, NVENC/NVDEC and thermal shutdown require separate testing. ASUS Armoury and custom fan curves are not enabled. Some optional NVML power and memory metrics may be unavailable on N1X.

## Repository layout and sources

```text
kernel/       complete Omarchy kernel recipe, configuration, signatures and P16 patches
acpi/         ACPI builder, transformations, ACPICA source archive and MIT license
config/       mkinitcpio/Limine configuration and systemd services
scripts/      build, installation, keyboard, temperature and verification tools
cuda/         CUDA C++ test program
sources.json  provenance and pinned upstream commits
SHA256SUMS    repository file checksums
tests/        failure handling and recovery regression tests
build/        local downloads and build outputs; excluded from Git
```

- [Omarchy ARM64/N1X installation](https://github.com/omacom/omarchy-iso/blob/quattro/N1X.md)
- [Nightly build and ARM64 publication](https://github.com/omacom/omarchy-iso/blob/quattro/.github/workflows/nightly-build.yml)
- [Omarchy kernel recipe](https://github.com/omacom/omarchy-pkgs/tree/9db7ac36d410aca6d571975be1a5a77677918569/pkgbuilds/linux-omarchy-aarch64)
- [P16 ACPI sources](https://github.com/pfeifferj/archlinuxarm-proart-p16/tree/3484cc008a9ee00b34c086c729e28e935cbc3430)
- [SPI-HID v5](https://lore.kernel.org/all/20261009-send-upstream-v5-0-384af01da3ee@chromium.org/)

Verify repository checksums with `sha256sum -c SHA256SUMS`. See [LICENSES.md](LICENSES.md) for licensing.

## Check the scripts

```bash
python3 -m unittest discover -s tests -v
PYTHONOPTIMIZE=1 python3 -m unittest discover -s tests -v
```

The tests use temporary filesystems to check invalid boot entries, complete EFI backups, interrupted installation recovery, boot-version mismatches, restored-checkpoint reuse, corrupted backups and operation with Python assertions disabled. Runtime validation remains active under Python optimization. The tests do not install a kernel or change the running system configuration.
