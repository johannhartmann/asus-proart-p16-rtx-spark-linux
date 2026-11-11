# Linux support for the ASUS ProArt P16 RTX Spark

Linux hardware enablement for the ARM64 ASUS ProArt P16 H7607BA with NVIDIA
N1X/RTX Spark: kernel patches, ACPI preparation, platform drivers, firmware
packaging and instructions for using the devices through normal Linux APIs.

The pinned package recipe uses Linux 7.2.8 and a reference ACPI transformation
recorded on BIOS H7607BA.300. The separate
[Linux 7.3 patch guide](improvements/README.md) includes physical results for
BIOS 303 and 305. These are separate installation paths. Drivers check ACPI
resources and firmware interfaces; BIOS version numbers describe test evidence,
not a list of permitted releases.

## Firmware compatibility

Compatible firmware can work across BIOS versions without a driver change.
The platform drivers select ACPI devices and check resource sizes, hardware
revisions, firmware protocols and reply bounds. Unsupported interfaces are
rejected by the affected driver instead of guessed from a BIOS version.
See [driver matching and checks](platform/README.md).

Build/source preparation and the CUDA test have no BIOS-version gate.
Board-specific diagnostic tools retain their hardware scope and operation-specific
module, DMA and firmware checks. These checks establish eligibility for the
operation; physical functionality still needs hardware qualification.

The historical ACPI override builder is deliberately narrower: its AML
byte-splices require exact verified input tables. Those inputs were recorded
on BIOS 300, but the builder checks their contents, not the BIOS label.
Changed AML needs a separately verified transformation; it is not a reason to
disable an otherwise compatible platform driver. The Linux 7.3 patch path has
its own ACPI integration and does not use that override package.

The [SSDT-removal preparation](docs/native-acpi-migration.md) provides an
offline staging tool and explicit native/legacy image checks. It creates a
separate test UKI with the same kernel/modules/command line and no ACPI override;
the legacy default and package dependency remain until the EC/battery/profile
comparison has passed. Preparing an image does not install it or qualify a boot.

## Choose an installation path

These are hardware-enablement sources for the **ARM64 H7607BA**, used on top
of a working Linux installation. They are not an installer for the AMD/x86 P16.

| Your starting point | Use | Validation and prerequisites |
| --- | --- | --- |
| Working ARM64 Arch/Omarchy with Limine/mkinitcpio and the reference ACPI inputs | [Pinned 7.2.8 packages](#build) and [installation](#installation-and-updates) below | The override builder requires the verified AML input layout recorded on BIOS 300. Preserve a working boot entry; driver candidates need their own fresh-boot qualification. |
| Integrating Linux 7.3 into a distribution | [Ordered kernel series](improvements/kernel/README.md), then [speaker routing](improvements/audio/README.md) and [telemetry](improvements/telemetry/README.md) | Physical evidence covers integrated 20-CPU BIOS 303/305 kernels; these versions are not an eligibility whitelist. Use the distro's packaging/boot process and the separate guide's ACPI policy. |
| Experimental DSP/AFE/provider changes | [Driver qualification](docs/driver-qualification.md) and the [DSP guide](platform/dsp/README.md) | Keep the matching kernel, AFE, DSP and SROOT ABI together. Published devices cannot be replaced live. |
| Another BIOS, kernel version or distribution | Check interface compatibility and qualify the relevant path | A BIOS label alone neither permits nor rejects a driver. Compatible interfaces need no BIOS-specific port; changed protocols or AML layouts need corresponding support. Do not apply the 7.3 series over an already patched tree. |

## Hardware enablement in this project

This table covers changes maintained or integrated here. Reference kernel
patches retain their upstream authorship; carrying a driver is not a claim
that this project wrote it. See [driver status](docs/platform-driver-status.md)
and [physical validation](improvements/VALIDATION.md) for implementation and
hardware-test limits.

| Area | Work in this repository | Driver/interface and qualification |
| --- | --- | --- |
| N1X coordinated s2idle | CPU/domain coordination, LPS0 timing, P16 admission and BIOS 305 timing fixes in patches 1120–1127 | Use the [Linux 7.3 sleep procedure](improvements/kernel/README.md#suspend-and-recovery). Physical results cover 20-CPU BIOS 303/305; 18-CPU admission remains tentative. |
| NVIDIA GPU boot integration | N1X GPU/IOMMU prerequisites, firmware-framebuffer policy, NVIDIA modules in the encrypted-disk initramfs and kernel/userspace version checks | Matching NVIDIA packages are required; see [GPU integration](#driver-and-userspace-interfaces). The NVIDIA GPU driver itself comes from NVIDIA. |
| ASUS keyboard and hotkeys | Integrated reference patches for backlight, Fn-lock and media keys; early `hid_asus` loading for the encrypted-disk prompt | Early input uses I2C HID and `hid_asus`; WMI provides hotkey events. Fn+Esc and the application key were tested; Fn+F7 external-display selection remains unvalidated. |
| PixArt touchpad `093a:4f01` | P16 libinput pressure/palm policy in `config/p16-touchpad.quirks`, plus the reference pressure-pad patch | Installed by `p16-platform-policy`, consumed by libinput. Touchpad operation was tested. |
| MT7925 Wi-Fi MLO | Backport of Andrei Rusu de Castro's upstream MLO membership correction, patch 9105 | Remains in the existing `mt7925e`/`mt76` stack. Simultaneous 5/6 GHz links and bounded connectivity tests passed; inter-AP roaming remains unvalidated. |
| GL9767 SD-reader resume | Bounded PCIe identity retry for the soldered P16 reader, patch 1121 | Included in the Linux 7.3 series; SD recovery after sleep was tested. This is a resume fix, not a new storage driver. |
| N1X USB4 and USB power management | Integrated reference ACPI/Type-C/USB4 and xHCI PM patches, plus packaged host-router power policy | Follow the kernel guide and keep its matching power policy. USB recovery was tested; USB4 docks, tunnelling and external displays remain unvalidated. |
| VEML3328 light/color sensor over SPI HID | Virtual-GPIO, deferred-IRQ and ACPI-reset fixes; serialized HID transactions and per-channel ALS scale backport | Exposed through HID/IIO and `iio-sensor-proxy`; see [sensor interfaces](#driver-and-userspace-interfaces). Light response and a resume cycle were tested; optical calibration remains unverified. |
| MT8901 / Cirrus speaker audio | CS35L56 firmware extraction/packaging, P16 DAPM routing, public PipeWire crossover graph and AFE SRAM/playback integration | Follow [speaker setup](improvements/audio/README.md). Local routing/tuning was tested; the public graph still needs its own listening validation. |
| Two HiFi5 DSPs and one HiFi1 DSP | `n1x_adsp`: signed-image preparation, SROOT loading, bounded IPC, HiFi1 ALSA playback and primary HiFi5 capture | Follow the [DSP guide](platform/dsp/README.md). Startup is opt-in; HiFi5 capture requires the matching AFE correction and hardware qualification. Complete audio and sleep qualification remains required. |
| NPU / SROOT integration | Provider snapshot and DKMS packaging, signed-firmware package, isolated-IOMMU boot service and DSP secure-loader interface | Follow [provider setup](docs/update-safe.md#npu-and-dsp). Inference driver/compiler/runtime development lives in the [companion project](https://github.com/johannhartmann/n1x-npu-linux). |
| SCP diagnostics | `n1x_scp`: firmware-log snapshots and checked version/descriptor queries | Debugfs interfaces are documented in the [SCP guide](platform/scp/README.md); sensor measurements use HID/IIO. |
| Pluton diagnostics | `n1x_pluton`: ACPI PFI transport and typed PCBI metadata queries | Use the [Pluton CLI](platform/pluton/pluton-info.py). Key operations and firmware updates are not implemented. |
| ASUS WMI, battery and fan reporting | ARM64 WMI integration, optional-capability guards, charge-threshold handling, firmware-profile/fan interfaces and critical-battery policy | Use [power interfaces](#driver-and-userspace-interfaces). Firmware retains fan control; the pinned policy requests a 100% charge threshold. |
| N1X thermal/power monitoring | `spark_hwmon` platform/firmware matching patches, hwmon integration and the repository's thermal monitor | Follow [telemetry setup](improvements/telemetry/README.md); read with `sensors` or `scripts/p16-temperatures`. Channel availability depends on firmware. |

## Driver and userspace interfaces

**Audio:** the MT8901 AFE and SoundWire machine driver feed the existing
CS42L43/CS35L56 ALSA/ASoC stack. `alsa-ucm-conf` supplies routing profiles;
PipeWire and WirePlumber provide desktop integration. The P16 additions are
Cirrus firmware preparation, machine DAPM routes, a public speaker-band
crossover graph, and the opt-in DSP-backed DL0/DL1 playback and UL1 capture frontends. See
[speaker integration](improvements/audio/README.md) and the
[DSP/AFE interface](platform/dsp/README.md). The three DSPs use `n1x_adsp`
and SROOT rather than a SOF firmware port. The native HiFi5 capture transport is implemented; beamforming and noise
suppression are not established firmware capabilities. Published DSP memory/provider leases remain retained until reboot;
complete analog-endpoint and candidate sleep qualification is still required.

**Light/color sensor:** `spi_hid_acpi` → `hid_sensor_hub` →
`hid_sensor_als` → IIO. The SPI/GPIO/reset fixes restore transport; the
[ALS backport](platform/als/README.md) preserves each channel's descriptor
scale. `iio-sensor-proxy` is the desktop-facing consumer. `n1x_scp` provides
[firmware diagnostics](platform/scp/README.md), not a duplicate sensor driver.

**NPU and DSP secure loading:** `n1x_npu_bootstrap` owns the DLA/SROOT endpoints
and exposes the DRM accelerator interface at `/dev/accel/accel0`. This
repository packages its provider and isolated-IOMMU startup service,
`n1x-platform-npu.service`, for DSP integration. The
[companion project](https://github.com/johannhartmann/n1x-npu-linux) maintains
the inference driver, native `t254` compiler, ONNX runtime and cuDLA backend.
Its standalone `n1x-npu.service` is an alternative package path; do not install
both service stacks for the same devices.

**Power and telemetry:** ASUS WMI exposes firmware profiles, charge thresholds
and fan RPM. The patched `spbm` driver exposes N1X temperature/power channels
through hwmon as `spbm_n1x`; `scripts/p16-temperatures` is the repository's
read-only monitor. Firmware retains fan control. The pinned policy package
requests a 100% charge threshold; the Linux 7.3 patch series imposes no threshold.

**Pluton:** `n1x_pluton` exposes typed PCBI metadata queries through
`/dev/n1x-pluton` and the packaged `n1x-pluton-info` diagnostic CLI. The
[protocol guide](platform/pluton/protocol.md) documents its allowlisted
commands. Key operations and firmware updates are not implemented.

**GPU integration:** NVIDIA supplies the open GPU modules, DRM/KMS and CUDA
userspace. This repository carries N1X IOMMU prerequisites, the
firmware-framebuffer boot policy, early NVIDIA initramfs loading and module/UKI
version checks. `cuda/vector-add.cu` and `scripts/check-cuda.sh` provide the
project's arithmetic smoke test (`sm_121`); compiler/device compatibility is
checked by CUDA rather than a BIOS-version restriction.
Hardware video encode/decode has no recorded qualification here. CUDA or
desktop rendering results do not establish that capability.

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

## Linux 7.3 hardware improvements (BIOS 303/305)

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

The steps below are for the reference-ACPI Arch/Omarchy package path. Start from a
working AArch64 installation with mounted `/boot`, Limine, mkinitcpio, matching
running-kernel headers and a working NVIDIA installation. Before any package
changes, prepare the [recovery entry](#recovery) below. This repository does
not provision a base OS, disk layout, encryption or firmware bootloader.

On a fresh Omarchy Nightly installation, run `omarchy update -y` before
installing dependencies. Required tools include `base-devel`, `dkms`, `git`,
`python`, `binutils`, `libarchive`, `gnupg`, `patch`, `7zip`, `innoextract` and
`wimlib`. The kernel's complete build dependency list is in
[`kernel/PKGBUILD`](kernel/PKGBUILD); the policy also requires UPower 1.91.5 or
newer. Install the distribution's NVIDIA open DKMS/kernel-module package and
matching `nvidia-utils`; this repository does not package NVIDIA's driver.
Secure Boot signing/enrolment is not automated here; a signing setup must cover
the kernel/UKI and external modules before using them under an enforcing system.

### 1. Check out and test the sources

Run builds as a normal user. Commands below start at the repository root;
subshells keep directory changes local to each build.

```sh
git clone https://github.com/johannhartmann/asus-proart-p16-rtx-spark-linux.git
cd asus-proart-p16-rtx-spark-linux
python3 -m unittest discover -s tests -v
```

### 2. Prepare board firmware and policy packages

```sh
sudo scripts/dump-acpi.sh
python3 scripts/build-acpi.py
python3 scripts/peripherals.py prepare
make -C packages MAKEPKG='makepkg --nodeps'
```

The dump creates `build/firmware`; it refuses to overwrite an existing capture.
The ACPI builder produces `build/acpi/kernel/firmware/acpi/SSDT.aml`, and
`peripherals.py prepare` downloads/verifies the ASUS archive and extracts three
Cirrus files into `build/speaker-firmware`. No Windows installer is executed.

| Package | Built package directory | Installed role |
| --- | --- | --- |
| `p16-acpi-firmware` | `build/packages/p16-acpi-firmware/` | Early BIOS-300 SSDT at `/usr/lib/firmware/acpi/p16/SSDT.aml` |
| `p16-speaker-firmware` | `build/packages/p16-speaker-firmware/` | Cirrus images and speaker-ID aliases under `/usr/lib/firmware/cirrus/` |
| `p16-platform-policy` | `build/packages/p16-platform-policy/` | Initramfs, boot/update guards, input and battery policy |

Only the generated SSDT is installed. A captured DSDT embeds boot-dependent
memory addresses and must never be included in an initramfs. OEM firmware and
machine captures remain local and are not redistribution grants.

### 3. Build the platform drivers and their firmware

Build the independent DKMS packages:

```sh
(
  for component in sensorhub als scp pluton; do
    (cd "platform/$component" && makepkg --nodeps) || exit 1
  done
)
```

Every build must succeed before continuing. The resulting packages remain in
the corresponding `platform/COMPONENT/` directory. `--nodeps` defers dependency
installation until the package transaction; it does not disable checksums/tests.
The sensorhub/ALS packages replace their corresponding modules: follow the
[ALS initramfs checks](platform/als/README.md) and do not retain competing copies.

For the SROOT provider, place the companion NPU checkout at `../n1x-lab/npu`
and use the matching revision linked by this checkout's
[qualification guide](docs/driver-qualification.md#reproducible-candidates).
Follow its [firmware acquisition procedure](https://github.com/johannhartmann/n1x-npu-linux/blob/master/docs/setup.md)
to obtain and verify `sources/sroot-v0.bin` and `sources/sroot-v1.bin`; copy
those two files into `platform/dsp/provider/firmware/`. Then:

```sh
python3 scripts/prepare-sroot-provider.py
(cd platform/dsp/provider/firmware && makepkg)
(cd platform/dsp/provider && makepkg --nodeps)
(cd platform/dsp && makepkg --nodeps)
```

The snapshot script rejects a provider/client header mismatch and writes the
provider PKGBUILD and receipt. Do not bypass that check or combine a newer
companion driver with an older DSP client. Outputs are respectively
`n1x-sroot-firmware-local`, `n1x-sroot-provider-dkms` and `n1x-adsp-dkms` in
the three build directories. Installing the DSP module does not enable boot.

If explicitly qualifying DSP firmware, prepare its signed images separately:

```sh
python3 scripts/prepare-platform-sources.py --fetch-vendor
python3 scripts/extract-platform-drivers.py
python3 scripts/prepare-dsp-firmware.py --dest platform/dsp/firmware
(cd platform/dsp/firmware && makepkg)
```

Extraction uses the pinned OEM inputs and produces `n1x-adsp-firmware-local`.
Leave DSP startup disabled during ordinary platform qualification.

Prepare and register the matching hwmon source without loading it:

```sh
bash scripts/prepare-spark-hwmon.sh
sudo dkms add "$PWD/build/spark_hwmon"
```

Skip `dkms add` if that exact source version is already registered; preserve
and investigate any source conflict instead of overwriting it. Target-kernel
DKMS builds happen after its headers are installed. The helper's printed
`install-dkms.sh` command reloads the running kernel's module and is not the
candidate-staging path. See [telemetry instructions](improvements/telemetry/README.md)
for the separate Linux 7.3 source path.

### 4. Build the matching kernel and headers

```sh
bash scripts/build-kernel.sh
```

This verifies upstream signatures with an isolated keyring and produces
`linux-p16-platform` and `linux-p16-platform-headers` in `kernel/` (unless
`PKGDEST` is set). To identify exact package filenames without guessing a
version, run `makepkg --packagelist` from each package's build directory.

For isolated candidate builds, use
`scripts/prepare-kernel-candidate.py --output DIR --build`; its packages go
under `DIR/packages/`, with a manifest recording input/output identities.
See [candidate qualification](docs/driver-qualification.md) for matching
platform and NVIDIA module builds. A successful build is not a boot result.

## Installation and updates

Use the exact newly built package paths, excluding stale versions and `.sig`
files. The sequence for the pinned package path is:

1. Install `p16-acpi-firmware`, `p16-speaker-firmware` and `p16-platform-policy`
   together with `pacman -U`. This installs board policy before the new kernel;
   keep the recovery copy and original kernel/modules intact. With the default
   `.pkg.tar.zst` package suffix and one fresh build in each directory:

   ```sh
   sudo pacman -U build/packages/p16-acpi-firmware/*.pkg.tar.zst \
     build/packages/p16-speaker-firmware/*.pkg.tar.zst \
     build/packages/p16-platform-policy/*.pkg.tar.zst
   ```

2. Install the update guard immediately, before another package transaction:

   ```sh
   sudo /usr/lib/p16-platform/install-guard
   ```

3. Install the kernel and headers together with the four independent DKMS
   packages, SROOT firmware/provider and DSP module. Include the optional DSP
   firmware only for an explicit candidate. For example, on a fresh build tree:

   ```sh
   sudo pacman -U kernel/linux-p16-platform-*.pkg.tar.zst \
     platform/sensorhub/n1x-sensorhub-dkms-*.pkg.tar.zst \
     platform/als/hid-sensor-als-dkms-*.pkg.tar.zst \
     platform/scp/n1x-scp-dkms-*.pkg.tar.zst \
     platform/pluton/n1x-pluton-dkms-*.pkg.tar.zst \
     platform/dsp/provider/firmware/n1x-sroot-firmware-local-*.pkg.tar.zst \
     platform/dsp/provider/n1x-sroot-provider-dkms-*.pkg.tar.zst \
     platform/dsp/n1x-adsp-dkms-*.pkg.tar.zst
   ```

   The kernel glob includes its headers. Review the expanded files first; use
   exact paths instead if the directories contain multiple builds. Required
   NVIDIA and `spbm` modules must also be installed for the new release.
4. Confirm every DKMS build succeeded. The managed hook checks module ABIs and
   then invokes `limine-mkinitcpio linux-p16-platform`. Its expected UKI is
   `/boot/EFI/Linux/omarchy_linux-p16-platform.efi`, with a generated Limine
   entry carrying `kernel-id=linux-p16-platform`. After correcting any failed
   hook, explicitly run:

   ```sh
   sudo dkms autoinstall -k TARGET_RELEASE
   sudo limine-mkinitcpio linux-p16-platform
   sudo p16-platform-update-check --all
   ```

   Replace `TARGET_RELEASE` with the release in the built package/manifest,
   not the old value from `uname -r`. A post-transaction failure can leave
   packages installed; stop and fix it before rebooting.
5. Keep the working entry as default and select the candidate manually for the
   first boot. The pinned ACPI-override image needs the packaged
   `acpi_osi="!Windows 2022"` policy, early SSDT, input/GPU modules and the existing
   root/encryption arguments. Preserve `console=tty0 acpi=nospcr`. Do not copy
   another machine's complete command line. Check the generated image before
   choosing it:

   ```sh
   sudo python3 scripts/verify-boot.py \
     --image /boot/EFI/Linux/omarchy_linux-p16-platform.efi
   ```

   This verifier is specific to the pinned ACPI-override package path; it checks
   image/menu hashes, the reference SSDT, payload and module dependencies. It
   does not check a BIOS label, establish Secure Boot trust or apply to the
   separate Linux 7.3 patch path.
6. Enable `p16-charge-limit.service` and, if using this provider package,
   `n1x-platform-npu.service` for subsequent boots. Restart UPower so its
   critical-battery power-off policy is active:

   ```sh
   sudo systemctl enable p16-charge-limit.service n1x-platform-npu.service
   sudo systemctl restart upower
   ```

The pinned battery policy requests 100%; adjust it through normal systemd
configuration overrides if desired. The Linux 7.3 patch path imposes no charge
threshold. Follow [update procedures](docs/update-safe.md) for subsequent
transactions and `.pacnew` files. DSP firmware publication remains opt-in;
retained allocations cannot be released by unloading a live instance.

## Verify the installation

After manually selecting the new entry, confirm the running release matches
the build, then inspect the interfaces changed here:

```sh
uname -r
dkms status
nvidia-smi
cat /sys/firmware/acpi/platform_profile_choices
cat /sys/power/mem_sleep
sensors
cat /proc/asound/cards
systemctl status n1x-platform-npu.service
journalctl -b -p err
```

Expected results: DKMS lists the required modules as installed for the new
release; NVIDIA reports the matching userspace driver; firmware profiles are
exposed; `[s2idle]` is selected; `spbm_n1x`/ASUS monitoring and the SoundWire
card appear. The NPU service must report successful startup. These checks
establish interfaces, not physical audio, inference accuracy or sleep recovery.

For the fully installed pinned platform bundle, the bounded diagnostic audit
writes a new report without installing/replacing modules or starting services:

```sh
sudo python3 scripts/verify-platform-install.py --report build/postboot-report.json
```

It performs firmware queries and fails on missing/mismatched components.
Choose a new report filename each run. For proof of a new boot, record
`cat /proc/sys/kernel/random/boot_id` beforehand and pass that old value with
`--after-boot-id`. The auditor is not a generic check for the Linux 7.3 path.

Physical qualification must cover early keyboard input, the packaged touchpad
policy, light response, corrected audio routes and numerical NPU output. Test suspend only in a disposable session
using the relevant [sleep guide](improvements/kernel/README.md#suspend-and-recovery)
and DSP restrictions. Promote a candidate only after those results are recorded.

## Recovery

Before changing packages, identify the UKI used by the working Limine entry.
Copy that **actual working image** to a separate filename; do not rename or
replace it. For example, replacing `WORKING.efi` with its real basename:

```sh
sudo cp -a /boot/EFI/Linux/WORKING.efi /boot/EFI/Linux/p16-recovery.efi
b2sum /boot/EFI/Linux/p16-recovery.efi
```

Save `/boot/limine.conf` separately and add a top-level entry using the full
128-character BLAKE2b digest just printed:

```text
/Omarchy-P16-Recovery
    protocol: efi
    path: boot():/EFI/Linux/p16-recovery.efi#BLAKE2B_DIGEST
```

Keep exactly one `timeout: 5` and `quiet: no` setting in the menu. Preserve
its existing working `default_entry`. Boot the recovery copy once before
relying on it, and retain that kernel's installed package, headers and modules:
a UKI copy alone does not preserve modules needed after mounting the root filesystem.
The managed wrapper does not rebuild this separate recovery copy.

If the candidate fails, select `Omarchy-P16-Recovery` in Limine and keep it as
the default while diagnosing. Do not unload NVIDIA during desktop use or
force-unload published DSP/provider modules. Repair/reinstall the failed
candidate's matching packages, rerun DKMS and the image checks, then retry
manually. If the menu itself is damaged, use a known-working ARM64 rescue
medium to mount the installed root and boot partitions and restore the saved
menu and recovery image; follow the distribution's unlock/mount/chroot procedure.

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

## Acknowledgements

A big thank-you to **Josephine Pfeiffer**, **Jordi Ibáñez** and
**Sean Kenneth Doherty** for helping improve Linux support on the ProArt P16.
Your contributions and shared experience are much appreciated!

## Installation field report

A second H7607BA (BIOS H7607BA.300, EC 2.16) completed the older
installation guide at commit
`4b34f31` on Nightly 2026.10.26.466, with `omarchy update -y` before
installing dependencies. On `7.2.8-23-omarchy-p16-asus`, the boot checks
passed; the keyboard and touchpad (`093A:4F01`) enumerated, and the
touchpad worked in use. Battery charge,
power profiles, the SoundWire card and NVIDIA driver 615.78.08 were present.
Audible playback, CUDA and suspend were not tested. This report predates the
package-based instructions above and does not validate the newer procedure.
