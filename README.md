# Linux support for the ASUS ProArt P16 RTX Spark

Kernel packages, ACPI preparation and platform drivers for the ARM64 ASUS
ProArt P16 H7607BA with NVIDIA N1X/RTX Spark. Board configuration targets BIOS H7607BA.300. The kernel
modules match ACPI devices and firmware interfaces; they do not use ASUS
product-name or BIOS checks.

## Components

| Path | Purpose |
| --- | --- |
| `kernel/` | Pinned Linux recipe, upstream patches and P16 integration patches |
| `acpi/` | Attributed ACPI builder and verified input transformations |
| `platform/` | DSP, SCP, Pluton, SPI HID and HID ALS drivers |
| `packages/` | Platform policy and locally prepared firmware PKGBUILDs |
| `config/` | mkinitcpio, Limine, module, udev and systemd policy |
| `scripts/` | Source preparation, build tools and manual diagnostics |
| `upstream/spi-hid/` | Dependency-pinned SPI HID review series |

For the standard ALSA/PipeWire DSP audio candidate, see [audio setup](docs/audio.md).

See [driver status](docs/platform-driver-status.md),
[matching policy](platform/README.md) and
[upstream requirements](docs/upstream-readiness.md) for scope and limitations.
The [GPU power measurements](docs/gpu-power.md) cover the bounded SysPL3
experiment and its qualification limits.
The [native vLLM setup](docs/vllm-qwen38.md) records the Unsloth NVFP4 and
DFlash2 configuration; model execution and throughput remain unvalidated.

## Linux 7.3 hardware improvements (BIOS 303)

A separate [hardware patch guide](improvements/README.md) provides an ordered
Linux 7.3 series with N1X prerequisites, coordinated s2idle and LPS0 timing,
ASUS WMI, battery controls, SPI-HID/light-sensor fixes and the upstream MT7925
MLO correction. It also includes speaker routing, an open PipeWire graph,
telemetry and source regression tests.

This is an alternative source-patch path for maintainers and other Linux
distributions. Follow its component guides separately from the pinned
BIOS 300/Linux 7.2.8 package procedure below. The BIOS 303 validation did not
use a DSDT override. Read the [physical results and limits](improvements/VALIDATION.md):
18-CPU admission is tentative, and the neutral public audio graph still
requires runtime and physical listening validation.

## Build

Use an AArch64 Arch Linux build environment with `base-devel`, `dkms`,
`python`, `binutils`, `libarchive` and the target kernel headers. Kernel builds
also require the dependencies in `kernel/PKGBUILD`. Build packages as a normal
user; installation is a separate root operation.

```sh
python3 -m unittest discover -s tests -v
make -C platform KDIR=/usr/lib/modules/$(uname -r)/build W=1 -j2
```

DSP, SCP and Pluton support normal Kconfig/Kbuild integration and external
module builds. Each driver's PKGBUILD supplies DKMS packaging. See
[platform build instructions](platform/README.md) for native KUnit tests.

On a fresh Omarchy Nightly installation, run `omarchy update -y` before
installing build dependencies so the online package databases are available.

Prepare board firmware locally:

```sh
sudo scripts/dump-acpi.sh
python3 scripts/build-acpi.py
python3 scripts/peripherals.py prepare
make -C packages MAKEPKG='makepkg --nodeps'
```

The package build skips runtime dependency installation; install the resulting
packages together. Source checksums remain enforced.

The ACPI package contains only the generated SSDT. A captured DSDT has
boot-dependent memory addresses and must not be installed into an initramfs.
OEM firmware and machine table dumps stay outside Git; package checksums
verify the local inputs and do not grant redistribution rights.

Build the kernel with `scripts/build-kernel.sh`. The recipe creates
`linux-p16-platform` and matching headers. For isolated candidate builds,
`scripts/prepare-kernel-candidate.py --output DIR --build` stages all source
and build output in a new directory. Signed upstream patches retain their
original authorship and notices.

## Installation and updates

Use `pacman -U` for the resulting firmware, policy, kernel/header and DKMS
packages. Do not mix modules from different kernel releases. Configure the
packaged update guard before the next package transaction:

```sh
sudo /usr/lib/p16-platform/install-guard
sudo systemctl enable p16-charge-limit.service
```

The battery policy writes 100 to existing `charge_control_end_threshold`
attributes through systemd-tmpfiles. Its udev rule also handles battery
appearance. Adjust the policy through the normal systemd configuration
override directories if a different charge limit is wanted.

At critical battery charge, the policy package configures UPower to power
off instead of suspending and continuing to drain the battery. Run
`sudo systemctl restart upower` after installing or upgrading this policy;
`scripts/verify-platform-install.py` checks the running daemon's action.

The NPU/SROOT provider has a separate package and boot service; see
[update procedures](docs/update-safe.md). DSP boot and playback remain
experimental and are disabled by default. Published DSP memory stays retained
until reboot because verified whole-core shutdown is unfinished.

Keep a tested recovery image and menu entry before selecting a new kernel.
A successful build is insufficient to promote a candidate. Check display,
USB/cameras, CPU topology, audio, sensors and numerical NPU results after boot.
The [update guide](docs/update-safe.md) describes the package hooks and checks.

## Sources and licenses

Input versions and hashes are recorded in `sources.json`,
`config/platform-sources.json`, `config/platform-oem.json` and driver-local
`provenance.json` files. Protocol notes describe verified fields and remaining
unknowns. Python is used for input preparation, offline tests and diagnostics;
firmware transport, memory ownership and playback callbacks run in C drivers.

The board enablement builds on
[Josephine Pfeiffer's Arch Linux ARM ProArt P16 work](https://github.com/pfeifferj/archlinuxarm-proart-p16).
See [LICENSES.md](LICENSES.md) for source and OEM asset terms. Contributor
attribution, license headers and existing patch sign-offs are preserved.

## Installation field report

A second H7607BA (SKU 90NB16A1-M00Y90; 64 GB, 3K OLED, 1 TB;
BIOS H7607BA.300, EC 2.16) completed the older installation guide at commit
`4b34f31` on Nightly 2026.10.26.466, with `omarchy update -y` before
installing dependencies. On `7.2.8-23-omarchy-p16-asus`, the boot checks
passed; the keyboard, touchpad (`093A:4F01`) and touchscreen/stylus
(`222A:5554`) enumerated, and the touchpad worked in use. Battery charge,
power profiles, the SoundWire card and NVIDIA driver 615.78.08 were present.
Audible playback, CUDA and suspend were not tested. This report predates the
package-based instructions above and does not validate the newer procedure.
