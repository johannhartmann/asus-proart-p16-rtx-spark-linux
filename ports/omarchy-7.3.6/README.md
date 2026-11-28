# Omarchy 7.3.6 for the ASUS ProArt P16

The target release is `7.3.6-10.1-omarchy-p16`. The base is Omarchy's signed
ARM64 kernel package `linux-omarchy 7.3.6-10` and the exact packaging tree
identified by its `.BUILDINFO` recipe digest.
[Omarchy source revision](https://github.com/omacom/omarchy-pkgs/tree/d9fff5fcc96e4539c009f56884a1d10631e1557a/pkgbuilds/linux-omarchy-aarch64).

The [overlay series](series) brings the kernel38 fixes onto that base.
Most patches apply with zero fuzz. The IPv4 RCU cleanup is already present.
The ASUS WMI rebase retains Omarchy's firmware-call serialization alongside
the BIOS .300 battery response handling. The AFE close rebase preserves the
fixed IRQ reservation and releases the closed PCM pointer.
The USB4 fix moves creation of the tunneled USB3 power-management link out
of the ACPI companion lookup. The USB device keeps its runtime PM reference
until the link has been installed. The normal disconnect path removes it.

| Hardware path | Integration |
| --- | --- |
| Platform providers | Keep the Omarchy MT8901 pinctrl, SSPM CI and ARM SMMUv3 in the kernel. Apply the P16 DSP power and translated DMA fixes. |
| Audio | In-tree AFE SRAM, SoundWire machine and SSPM paths with the P16 corrections. Build the packaged DSP consumer and its SROOT provider against the new ABI. |
| Input and telemetry | In-tree ACPI SPI-HID and ambient light sensor, ASUS WMI modules, and rebuilt SCP, Pluton and SPBM modules. |
| Camera and resume | Keep the bounded UVC DMA allocations, PCIe hotplug resume, SDHCI IRQ ownership and Lockdep fixes. |
| NVIDIA | Rebuild the five 620.70.06 modules with the existing P16 patch package and Omarchy's seven display patches. Retain the corresponding NVIDIA userspace, Tegra EGL component and NVENC launcher. |

## Build

Use the authenticated Linux 7.3.6 archive and NVIDIA 620.70.06 DKMS archive,
the Omarchy package directory at the revision above, the signed matching
Omarchy headers package and a checkout containing the pinned
`spark_hwmon` commit. The input checks also verify the archive and patch
digests. Run the build as the workspace owner.

```sh
port="$PWD/ports/omarchy-7.3.6"
python3 "$port/prepare.py" --recipe "$omarchy_recipe" \
  --linux-source "$linux_archive" --stock-headers "$omarchy_headers" \
  --output "$candidate"
tree="$candidate/linux-7.3.6"
make -C "$tree" -j"$(nproc)" Image vmlinuz.efi modules
python3 "$port/build-drivers.py" --recipe "$omarchy_recipe" \
  --nvidia-package "$nvidia_archive" --hwmon-source "$hwmon_repo" \
  --kernel-tree "$tree" --output "$candidate/drivers"
cd "$port"
P16_KERNEL_TREE="$tree" P16_DRIVER_TREE="$candidate/drivers" makepkg --nodeps
```

The split packages install a separate kernel release and headers. The driver
package includes the Omarchy NVIDIA patch files and a release-specific DKMS
override so a rebuild on this kernel retains them. Release-specific DKMS
overrides keep SPI-HID and the ambient light sensor supplied by the kernel
package and leave their DKMS packages usable for older kernels. Stage the
packages together in the updated Omarchy snapshot with the matching NVIDIA
userspace. Build and verify a separate UKI and keep the qualified kernel38
image and root available until native display and suspend/resume pass.
