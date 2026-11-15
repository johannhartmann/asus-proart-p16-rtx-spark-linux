# Package updates and recovery

Use the kernel/header and DKMS packages together. Keep a tested recovery UKI
and its BLAKE2b-pinned Limine entry before updating a candidate. Existing
recovery images are not rebuilt by the managed-kernel wrapper.

## Boot-partition retention

Keep the running/default kernel, the next candidate and one tested recovery
image, together with their matching installed kernels, headers and modules.
After a replacement is qualified, remove obsolete kernel, header and per-kernel
driver packages explicitly through pacman. Review dependencies first; preserve
the shared SDK, firmware and current DKMS source packages.

Deleting only an old EFI image is insufficient: the managed updater also
discovers installed `linux-p16-platform*` packages through their `pkgbase`
files and can rebuild those images. Remove obsolete package registrations and
menu entries too. Verify a proposed menu and all retained image hashes before
unlinking old images. Keep any diagnostic archives outside `/boot` and allow
space for another complete UKI while an update is being written.

The [15 November cleanup record](evidence/boot-cleanup-20261115.json) retains
kernel34 as default, kernel35 as the candidate and kernel23 as recovery. Five
obsolete/duplicate EFI images were archived and thirteen old kernel-related
packages removed. Only kernel34 and kernel35 remain in the managed rebuild
set. `/boot` has about 1.3 GiB free; the three retained image hashes, 25,548
protected files and loaded driver identities were checked without a reboot.

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

NPU and DSP modules load through ACPI modaliases. Firmware loading and
readiness belong to the C driver probe paths. There is no startup service or
Python dependency. Before migrating a passthrough-default kernel, include
[`n1x-translated-dma.patch`](../kernel/n1x-translated-dma.patch); normal DMA
translation must be established before binding, not by a userspace sysfs write.
Keep the working kernel and its startup configuration until that migration is
qualified. Do not remove a live driver's DMA domain or force an unload.
When adopting normal ACPI loading, select the qualified DMA-capable kernel
for normal boots as well; older passthrough-default kernels still need their
original startup configuration.

Use a new DKMS source version when changing the provider source snapshot;
changing only the package release can reuse old builds under the same DKMS
cache identity. The helper-free provider package uses source version 0.1.1
and the existing firmware-provider ABI v5. For a retained older kernel that
lacks the translated-DMA policy, keep a backup of its startup configuration
alongside its original module files. A preserved EFI image alone does not
preserve compatibility with globally changed module-loading configuration.

```sh
modinfo -k "$(uname -r)" n1x_npu_bootstrap
journalctl -b -k
```

DSP firmware publication retains its DMA/provider leases until checked
shutdown succeeds. The source checkout provides
`scripts/qualify-dsp-reload.py` for explicit developer reload qualification;
it is not installed by the driver packages. Never force module removal after
a failed or uncertain hardware stop. NVIDIA display modules must also remain
loaded during desktop use.

## Qualify a candidate

Build and verify a separate candidate UKI, preserving the current primary and
recovery images. Select its entry in Limine for the first boot. Check the new
kernel release, CPU topology, USB/cameras, display/input, audio and sensors.
Run a numerical NPU workload and inspect service/kernel errors before promoting
that candidate. A successful package build or UKI hash check alone does not
qualify the hardware.
