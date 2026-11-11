# Package updates and recovery

Use the kernel/header and DKMS packages together. Keep a tested recovery UKI
and its BLAKE2b-pinned Limine entry before updating a candidate. Existing
recovery images are not rebuilt by the managed-kernel wrapper.

## Package ownership

`packages/Makefile` stages explicit source manifests and runs the three
PKGBUILDs. It does not copy installed host configuration. `p16-acpi-firmware`
contains only the locally generated SSDT. `p16-speaker-firmware` contains the
three pinned OEM assets and their speaker-ID aliases. OEM assets are local
build inputs; do not publish the resulting firmware packages without the
necessary rights.

`p16-platform-policy` owns mkinitcpio, Limine, module, udev and systemd policy.
Local `/etc` configuration is tracked through pacman's backup mechanism.
Private update helpers are installed under `/usr/lib/p16-platform`; public
checks are under `/usr/bin`. Install the packages with `pacman -U`, then run:

```sh
sudo /usr/lib/p16-platform/install-guard
sudo systemctl enable p16-charge-limit.service
```

The guard saves the previous hook/configuration under
`/var/lib/p16-platform/boot-hook-backup`, installs the packaged mkinitcpio hook
and adds its `NoUpgrade` entry. Its pre-transaction check blocks package
changes if this protection is missing. Restore it with `install-guard` after a
configuration refresh. Review mkinitcpio hook changes supplied as `.pacnew`.

## Kernel update checks

`linux-p16-platform` requires its matching headers. Pacman runs DKMS before the
managed mkinitcpio hook, then the platform postcheck. Managed kernels are
identified by `pkgbase`, not a release-number allowlist. The wrapper leaves
other images alone.

```sh
sudo p16-platform-update-check --all
```

The default legacy postcheck validates the ACPI override allocator, required
configuration, module ABIs/dependencies, NVIDIA kernel/userspace versions and
embedded SPI HID modules. That profile requires the exact reference SSDT and
rejects other ACPI overrides. Firmware GNVS addresses change between boots;
a captured DSDT can disable USB/cameras and break CPU-topology enumeration.

For a separately staged native-ACPI candidate, policy 1.3.0 adds an explicit
`--acpi-mode native` to the image checker. That profile requires absence of
all ACPI override files and does not require the override allocator/table-upgrade
option. Module, kernel, configuration and command-line checks remain active.
Automatic update hooks still use legacy mode; installing this source preparation
does not switch an existing kernel to native ACPI. See the
[removal and qualification procedure](native-acpi-migration.md) before changing
the default or removing `p16-acpi-firmware`.

The Limine policy verifies Linux image hashes and preserves unrelated entries.
It keeps a valid selected P16 image, or selects `Omarchy-P16-Recovery` when the
selected image fails validation. A failed check remains an error even if a
recovery default was selected. No validated recovery means the menu is left
unchanged. A post-transaction failure cannot roll back an already completed
package transaction.

## NPU and DSP

Prepare the NPU/SROOT provider source with
`python3 scripts/prepare-sroot-provider.py`, then build its PKGBUILD under
`platform/dsp/provider`. Obtain the signed inputs as described in
[the local firmware package](../platform/dsp/provider/firmware/README.md).

Enable `n1x-platform-npu.service` for normal boot loading after installing the
matching provider and firmware packages. Its helper discovers supported ACPI
devices and checks isolated IOMMU groups before selecting DMA domains. Startup
failure remains visible in the journal; the helper does not reset or retry
uncertain firmware state.

```sh
systemctl status n1x-platform-npu.service
journalctl -b -u n1x-platform-npu.service
modinfo -k "$(uname -r)" n1x_npu_bootstrap
```

DSP startup is explicit and disabled by default. Published buffers remain
retained until reboot. Do not unload or replace a published instance to test a
new build. NVIDIA display modules must also remain loaded during desktop use.

## Qualify a candidate

Build and verify a separate candidate UKI, preserving the current primary and
recovery images. Select its entry in Limine for the first boot. Check the new
kernel release, CPU topology, USB/cameras, display/input, audio and sensors.
Run a numerical NPU workload and inspect service/kernel errors before promoting
that candidate. A successful package build or UKI hash check alone does not
qualify the hardware.
