# Linux 7.3 hardware patch series

Target: ASUS ProArt P16 **H7607BA, NVIDIA N1X/RTX Spark, AArch64**.
This is not the AMD/x86 ProArt P16. BIOS 303 and 305 have physical test evidence;
see the validation record for the different scope of each test.

## Inputs and patch order

`series` applies to the pristine **Linux 7.3** release. It includes the required
N1X/MediaTek and SPI-HID prerequisites, not just our final fixes. Patches are
copied from the pinned sources, with narrowly documented follow-ups recorded in
[`../sources.json`](../sources.json). Existing From/author/sign-off notices
remain intact. The base platform work belongs to NVIDIA and the kernel authors;
the additions build on Johann Hartmann and Josephine Pfeiffer's P16 work.

| Patches | Purpose |
|---|---|
| 0605, 0608, 0803, 0804 | Thunderbolt and battery-hook prerequisites |
| 1000-1113 | N1X/MediaTek platform, EC, power, audio, USB4, keyboard and touchpad support from the reference series |
| 1120 | Defer PCI hotplug events across system resume (Cole Leavitt) |
| 1121 | Bounded resume identity retry for the soldered P16 SD reader |
| 1122 | Coordinated CPU/domain s2idle, ported from NVIDIA's hierarchy/lifecycle work |
| 1123 | In-tree LPS0 late-suspend/early-resume notifications and EC timing |
| 1124 | Automatic P16/N1X hardware admission, retaining firmware compatibility checks |
| 1125 | Preserve existing DRIPS latency for non-coordinated fallback states |
| 1126 | Accept validated BIOS 305 enabled parent LPI profiles and the exact paired system timing sentinel |
| 1127 | Saturate fallback DRIPS latency addition to preserve U32_MAX without wrapping |
| 2110-2120 | SPI-HID transport prerequisites |
| 9100 | ASUS WMI on ARM64, battery response handling and preserving the charge threshold |
| 9101 | MT8901 interrupt-only GPIOs 182-208, including sensor GPIO 190 |
| 9102 | Deferred ACPI IRQ lookup for SPI-HID |
| 9103 | Architecture/capability guards for optional ASUS LPS0, i8042 and fan initialization |
| 9104 | Invoke the sensor's ACPI `_RST` on its saved namespace handle |
| 9105 | Keep MT7925 MLO firmware membership consistent when adding a secondary link |

1122 is a consolidated port based on NVIDIA NV-Kernels PR586 at
`2562f5f1d1cecfd2047d3810d4bf5626366f1d32`, plus PR599/601, with local
P16 admission and suspend-only restrictions. Attribution is not a new sign-off.

## Apply and configure

Install your distro's kernel build prerequisites (including a C compiler,
Python3 and ASan/UBSan runtimes for tests). Download Linux 7.3 from kernel.org and
verify its release signature using kernel.org's published verification process.
Extract it in a new work directory; do not apply over the original repo's 7.2
series or over a distro tree that already includes these patches.

From a checkout of this fork, as a regular user:

```sh
patch_dir="$PWD/improvements/kernel"
cd /path/to/pristine/linux-7.3
(
while IFS= read -r file; do
  patch --batch --fuzz=0 -p1 < "$patch_dir/$file" || exit 1
done < "$patch_dir/series"
)
```

Run this patch block on its own and check its exit status before continuing.
Every patch must succeed. If one fails, stop and discard/recreate the partially
patched work tree; do not build it. For another kernel version, a maintainer
must rebase the series and run its tests.

Start with a working N1X distro config, or the public `config.reference` supplied
here. Merge `config.fragment` with the kernel's `scripts/kconfig/merge_config.sh`
and run `make olddefconfig`. Confirm the fragment's requested settings survive;
a fragment alone is not a complete bootable config. The reference is the
public configuration used for source tests, not a promise about other distros.

```sh
cp "$patch_dir/config.reference" .config
scripts/kconfig/merge_config.sh -m .config "$patch_dir/config.fragment"
make olddefconfig
bash "$patch_dir/check.sh" "$PWD"
```

Then build `Image` and modules using your distro's kernel packaging procedure.
Install matching modules/headers and a separate boot entry with its normal
initramfs, firmware, signing and recovery mechanisms. Keep a working kernel
entry until boot, audio and suspend are tested. NVIDIA's open GPU modules must
match the kernel and userspace driver; the tested driver was 615.78.08. This
series does not bundle that separate driver or a bootloader installer.

Apply the [audio route patch](../audio/README.md) before compiling if using
in-tree speaker routing. It is kept separate from this base series so an
existing DKMS replacement is not also installed for the same driver.

## Hardware interfaces

Load `asus_nb_wmi` and `spi_hid_acpi` if module autoload does not bind them.
Battery thresholds appear under `/sys/class/power_supply/BAT*/charge_control_end_threshold`.
9100 exposes/preserves the control; it does not impose 80% at boot. Choose a
charge limit with the desktop or power manager supported by your distro.

`/sys/firmware/acpi/platform_profile*` exposes firmware profiles. `sensors` or
hwmon readers can display ASUS fan RPM. Firmware still manages fan speed;
9103 avoids querying unsupported optional fan curves. It does not add a custom
fan daemon. Use the [telemetry patch](../telemetry/README.md) for N1X power data.

The light sensor should appear as a HID sensor hub and an IIO illuminance
channel. A desktop can consume it through `iio-sensor-proxy` (`monitor-sensor`).
Keyboard/media-key support is included in the prerequisites. Fn+Esc toggles
Fn-lock; the ASUS application key is exposed for the desktop to bind. Fn+F7's
external-display action still needs validation with a connected monitor.

## Suspend and recovery

Use `s2idle` (`cat /sys/power/mem_sleep` shows the selected mode in brackets).
The coordinated path matches ASUS ProArt P16 plus the N1X ACPI device; it is
not pinned to a BIOS number. OSLPI acknowledgement, PSCI OSI availability,
complete CPU coverage and the expected firmware state contracts must still pass. Other
firmware can be rejected safely rather than entering an incompatible hierarchy.
1126 accepts uniformly enabled known parent descriptors as well as the BIOS 303
masked form. Only the system level may use the exact enabled, paired `U32_MAX`
timing sentinel; firmware timing values and finite system QoS limits are preserved.
It does not write MPEL, ELST or SYSRAM. `check.sh` automatically includes the
actual-function BIOS 305 policy and system-governor regression harnesses.
Ordinary CPU idle does not use the coordinated shared-domain suspend states.

For troubleshooting, boot with `acpi.n1x_coordinated_s2idle=0` to disable the
coordinated path. `=1` cannot force support on unrelated hardware. No DSDT
replacement or out-of-tree LPS0 module was used for our BIOS 303 validation.
See [validation and limits](../VALIDATION.md) before interpreting sleep results.

License: Linux patches retain their source licenses (GPL-2.0-only as packaged);
tests preserve SPDX notices. See the root `LICENSES.md`.

## MT7925 MLO follow-up

Patch 9105 is the unmodified upstream commit
[`dd3f17ef69ed`](https://github.com/torvalds/linux/commit/dd3f17ef69ed6d0085cd94a15b9dec227b4ebfb1),
authored by Andrei Rusu de Castro. While adding a secondary link, the two
firmware station updates now contain the same published and pending MLD links.
The pending link is published to host state only after setup succeeds; record
capacity and primary-first ordering are retained. No band, BSSID, VPN or
roaming setting is changed. In particular, 6 GHz remains available.

`test_mld.py` extracts the real TLV function and firmware structure from the
prepared tree and compiles a native C harness with ASan/UBSan and `-Werror`.
The old function fails with inconsistent member counts 1/2; the fixed function
passes pending/published membership, absent station/BSS, duplicates, capacity,
primary fallback and both real add-time caller checks. `check.sh` includes it.
See the validation record for measured connectivity and remaining limits.

The coordinated-sleep series admits 18- and 20-CPU N1X configurations when
all existing hardware, ACPI/LPI hierarchy, register, state and CPU-coverage
checks pass. The 18-CPU admission is tentative: it assumes those SKUs retain
the same firmware contracts with two fewer CPUs. Physical validation here is
limited to the 20-CPU H7607BA BIOS 303/305 configurations; accepting a CPU count is
not a claim of working sleep or power draw on an 18-CPU unit. Other CPU counts
and incompatible firmware retain the normal non-coordinated fallback.

An owner of an 18-CPU model can help validate this assumption by sharing the
exact model/BIOS, `lscpu`, the boot log containing the coordinated-admission
message, and results from a manually controlled suspend/resume test. Review
logs for personal identifiers before sharing. A prepared firmware-table capture
with its ACPI/LPI and CPU topology would permit a direct structural comparison.
