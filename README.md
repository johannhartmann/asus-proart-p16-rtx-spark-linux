# Linux support for the ASUS ProArt P16 RTX Spark

Linux hardware enablement for the ARM64 ASUS ProArt P16 H7607BA with NVIDIA
N1X/RTX Spark: kernel patches, ACPI preparation, platform drivers, firmware
packaging and instructions for using the devices through normal Linux APIs.

The pinned package procedure targets BIOS H7607BA.300 and Linux 7.2.8. The
separate [Linux 7.3 patch guide](improvements/README.md) includes physical
results for BIOS 303 and 305. Follow the procedure for your kernel and firmware;
these are separate installation paths. Platform modules match ACPI resources
and firmware interfaces; board policy and firmware preparation can be P16-specific.

## Hardware and Linux support

The inventory below combines the repository's driver work, recorded hardware
tests and a read-only inventory of a 20-CPU H7607BA on BIOS 300 on 2026-11-11.
**Enumerated** means Linux exposes the device; it does not establish that every
function has been physically tested. Memory, storage and CPU counts can differ
between SKUs. See [driver status](docs/platform-driver-status.md) for source
implementation limits and [physical validation](improvements/VALIDATION.md)
for the tested kernel/BIOS combinations.

| Hardware found | Driver / Linux interface | Support and use |
| --- | --- | --- |
| N1X ARM CPU complex: 10 Cortex-X925 + 10 Cortex-A725 cores on the inventoried unit | ARM64, cpufreq, cpuidle and ACPI/PSCI | All 20 CPUs online; ordinary ARM64 applications use the normal scheduler. Inspect topology with `lscpu`. 18-CPU coordinated-sleep support remains tentative. |
| Blackwell RTX Spark N1X GPU, PCI `10de:2e03`, CUDA capability 12.1 | NVIDIA open kernel modules, DRM/KMS and CUDA | Desktop rendering and numerical CUDA execution tested with NVIDIA 615.78.08. Use normal graphics applications or CUDA programs; see [GPU usage](#gpu-display-and-cuda). |
| Internal OLED display and brightness control | NVIDIA DRM/KMS; `/sys/class/backlight/nvidia_0` | Internal desktop active and backlight interface present. Use desktop display/brightness settings. External display combinations still need separate validation. |
| ASUS keyboard `0b05:4b42`, backlight and hotkeys | I2C HID, `hid_asus`, `asus_nb_wmi`, evdev and LED class | Normal keyboard input; Fn+Esc and ASUS application key tested. Keyboard brightness is exposed as `asus::kbd_backlight`. Bind the application key in the desktop; Fn+F7 external-display selection remains unvalidated. |
| Touchpad `093a:4f01` | `i2c_hid_acpi`, `hid_multitouch`, libinput | Touchpad working in use; configure pointer and gestures through libinput/desktop settings. The extra vendor HID collection does not establish DialPad support. |
| Touchscreen and stylus `222a:5554` | I2C HID, `hid_multitouch`, evdev | Touch and stylus input devices enumerate. Use touch/pen-aware applications; pressure, buttons and complete pen behavior need physical qualification. |
| MediaTek MT7925 Wi-Fi, PCI `14c3:7925` | `mt7925e` / `mt76`, cfg80211 | Use NetworkManager or another normal network manager. The Linux 7.3 series includes the upstream MLO correction; simultaneous 5/6 GHz links and connectivity were tested. Inter-AP roaming was not validated. |
| MediaTek Bluetooth, USB `13d3:3602` | `btusb`, `btmtk`, BlueZ | Pair through desktop Bluetooth settings or `bluetoothctl`. Bluetooth audio and reconnection after one s2idle cycle were tested. |
| NVMe storage: Sandisk `15b7:5063` and Samsung `144d:a80f` controllers on the inventoried unit | `nvme`, Linux block devices | Both drives bound and exposed as normal NVMe disks. Use `lsblk` and the distribution's storage tools; installed models/capacities vary. |
| Genesys Logic GL9767 SD UHS-II / SD Express reader, PCI `17a0:9767` | `sdhci_pci`, `sdhci_uhs2` | Reader bound; SD recovery after sleep recorded. Insert a card and use normal removable-storage tools. Each advertised speed mode, including SD Express, is not separately qualified. |
| USB host controllers, USB-C and USB4 routers | xHCI, `ucsi_acpi`, Type-C and `thunderbolt_platform` | USB peripherals enumerate; a connected USB 3 device remained readable after a tested sleep cycle. Use normal USB devices; USB4 docks, tunnelling and external displays remain unvalidated. |
| ASUS FHD RGB and IR webcam, USB `636e:0bdb` | `uvcvideo`, V4L2 | RGB and IR video/metadata nodes enumerate. Select the RGB camera in a camera/conferencing application; use `v4l2-ctl --list-devices` to identify nodes. Image quality and IR authentication are not qualified. |
| Camera-associated proximity / attention sensor | `hid_sensor_prox`, IIO | A separate `prox` IIO device exposes proximity and attention channels. Applications can consume those channels; automatic presence detection or login policy is not supplied. |
| VEML3328 ambient-light / color sensor behind SCP and SPI HID (`MSFW1111`) | `spi_hid_acpi` → HID sensor hub → `hid_sensor_als`, IIO | Illumination responds to cover/light changes and was read after resume. Color temperature and chromaticity channels are exposed with descriptor-specific scales. Use [sensor interfaces](#sensors-fans-and-power); absolute optical calibration remains unverified. |
| MT8901 audio front end and SoundWire bus; Cirrus CS42L43 codec and CS35L56 amplifiers | ALSA/ASoC, UCM, PipeWire and WirePlumber | Internal speaker/headphone routing and jack switching tested with local firmware/tuning. Microphone capture interfaces exist; qualify each endpoint. See [audio usage](#audio-and-the-three-dsps) for required firmware and the public speaker graph's limits. |
| NVIDIA HDMI/DisplayPort audio (`NVDA2014`) | `snd_hda_acpi`, `snd_hda_codec_tegrahdmi`, ALSA | Four HDMI/DP playback PCMs enumerate. Select the corresponding desktop output when a display is connected; physical external-output playback remains unvalidated. |
| Two Cadence HiFi5 DSPs (`NVDA8301`, `NVDA8302`) and one HiFi1 DSP (`NVDA8303`) | `n1x_adsp`, SROOT secure loading and AFE-owned SRAM | Signed-firmware boot and bounded IPC implemented; experimental HiFi1 route-2 ALSA playback client. HiFi5 microphone processing/beamforming is not implemented. Firmware startup is opt-in; complete audio and sleep qualification is still required. |
| NPU/DLA (`NVDA200A`) and shared SROOT secure firmware service (`NVDA8600`) | `n1x_npu_bootstrap`, DRM accelerator `/dev/accel/accel0` | Numerical inference tested. The companion project provides an FP16/INT8 compiler, ONNX runtime and cuDLA backend; see [NPU usage](#npu-inference). SROOT also authenticates the audio DSP images. |
| SCP sensor microcontroller (`NVDA8200`) | `n1x_scp`, debugfs diagnostics | Read firmware logs, version and checked sensor descriptors. Measurements use the standard HID/IIO sensor path; see [SCP diagnostics](#scp-and-security-device-diagnostics). |
| Pluton security processor (`NVDA8601`) | `n1x_pluton`, `/dev/n1x-pluton` | Typed PCBI running-firmware, service and protocol-version queries implemented. Key operations and firmware updates are not implemented. This driver does not provide a TPM interface. |
| Separate TPM 2.0 (`NTC0702`) | `tpm_crb_acpi`, `/dev/tpm0`, `/dev/tpmrm0` | TPM class device enumerates. Standard TPM2 tools can use it; measured boot, sealing and disk-unlock workflows need their own qualification. |
| Battery, AC/USB-C supplies, firmware profiles, lid/power buttons and fans | ACPI power-supply/input interfaces, ASUS WMI, platform profile and hwmon | Battery reporting, charge-threshold interface, `quiet`/`balanced`/`performance` profiles and CPU/GPU fan RPM exposed. Use desktop power settings and [power interfaces](#sensors-fans-and-power); firmware controls fan speed. |
| N1X power and thermal telemetry (`NVDA8810`) | `spbm` from `spark_hwmon`, hwmon `spbm_n1x` | SoC/CPU/GPU/DLA temperatures and system/component power readings available to `sensors` and desktop monitors. Channels depend on firmware; see [telemetry setup](improvements/telemetry/README.md). |

The kernel also supplies the PCIe, I2C, SPI, GPIO/pinctrl, interrupt, IOMMU and
power-domain infrastructure used by these devices. ACPI discovery alone does
not imply a usable driver: for example, the inventoried `NVDA0820` platform
control device had no bound driver. The inventory does not claim support for
undocumented vendor functions.

## Using the hardware

Install the matching kernel, modules and locally prepared firmware first using
one of the build paths below. The commands here inspect or use those installed
interfaces; they are not a replacement for driver installation. Device numbers
and desktop node names can change between boots.

### GPU, display and CUDA

Use normal Wayland/X11 display settings for the panel and connected displays.
Check the loaded GPU driver and run the repository's small CUDA vector-add
check after installing an ARM64 CUDA toolkit with `sm_121` support:

```sh
nvidia-smi
bash scripts/check-cuda.sh
```

The CUDA check expects `nvcc` under `/opt/cuda` and currently checks for BIOS
300. On another supported BIOS, compile the same test directly:

```sh
/opt/cuda/bin/nvcc -O2 -std=c++17 -arch=sm_121 cuda/vector-add.cu -o /tmp/p16-vector-add
/tmp/p16-vector-add
```

Use the distribution/vendor's matching NVIDIA kernel and userspace packages.
Unified system memory is not a separate pool of dedicated VRAM; an unsupported
NVML memory counter does not establish missing GPU support.

### NPU inference

Follow the companion [N1X NPU setup](https://github.com/johannhartmann/n1x-npu-linux/blob/master/docs/setup.md)
for firmware acquisition, the native `t254` compiler and runtime. The
[demos](https://github.com/johannhartmann/n1x-npu-linux/blob/master/demo/README.md)
cover super-resolution, denoising, classification and ONNX execution. After
following that project's installation procedure, run from its checkout:

```sh
./demo-onnx --model emotion --precision fp16 --output-dir results/emotion-fp16
./demo-onnx --model emotion --precision int8 --output-dir results/emotion-int8
```

For applications, use its `N1xInferenceSession` ONNX interface or cuDLA backend;
the kernel interface is `/dev/accel/accel0`. Operator coverage and model
compatibility are documented in that project. This repository's packaged DSP
provider uses `n1x-platform-npu.service`; the companion's standalone package
uses `n1x-npu.service`. Choose one matching provider/package path, following
[provider installation](docs/update-safe.md#npu-and-dsp), rather than installing
both service stacks for the same hardware.

### Audio and the three DSPs

Applications use the `mt8901-soundwire` ALSA card through PipeWire/WirePlumber
and its UCM profiles. Inspect available endpoints with:

```sh
aplay -l
arecord -l
wpctl status -n
```

Install the board's locally extracted Cirrus firmware and matching machine
routes. For speakers, follow the [speaker routing and PipeWire guide](improvements/audio/README.md):
the physical outputs serve different speaker bands. Its public crossover graph
requires mapping checks and physical validation; the locally tested OEM-derived
tuning is not redistributed. Headphone, Bluetooth and HDMI outputs use their
normal desktop selections.

The [DSP driver guide](platform/dsp/README.md) describes secure firmware loading
and the experimental HiFi1 playback path. Two HiFi5 cores also boot, but
microphone DSP processing, beamforming and noise suppression are not supplied.
DSP publication retains DMA memory and provider references until reboot.
Default published instances block system sleep; any candidate retention-sleep
path requires separate qualification. Keep the ordinary audio/boot path while
testing matching DSP, AFE and SROOT candidates.

### Sensors, fans and power

Use `sensors` for fan RPM, temperatures and power channels. The repository's
thermal monitor also reports the limits actually provided by firmware:

```sh
sensors
python3 scripts/p16-temperatures --watch
cat /sys/firmware/acpi/platform_profile_choices
cat /sys/firmware/acpi/platform_profile
cat /sys/class/power_supply/BAT*/charge_control_end_threshold
```

Choose a firmware profile or charge threshold with the distribution's power
manager. The pinned policy package requests a 100% charge threshold; the Linux
7.3 patch series exposes the control without imposing a threshold. An exposed
attribute can still return an error on a particular running firmware/driver
combination. Fan RPM reporting leaves fan control with the firmware.

For light measurements, install `iio-sensor-proxy` and use `monitor-sensor`;
automatic brightness depends on desktop support. To identify the light and
camera proximity devices directly:

```sh
for device in /sys/bus/iio/devices/iio:device*; do
  printf '%s: ' "$device"
  cat "$device/name"
  ls "$device"/in_*
done
```

IIO raw values must be interpreted using each channel's scale and offset.
The [ALS backport](platform/als/README.md) fixes differing illumination,
color-temperature and chromaticity scales. The SCP diagnostic mailbox does
not provide an additional sensor device.

### SCP and security-device diagnostics

With the SCP driver loaded and debugfs mounted, administrators can read
`/sys/kernel/debug/n1x_scp/firmware_log` and `status`. Its `firmware_version`
and `sensor_descriptors` files perform bounded firmware queries when mailbox
support is enabled. See the [SCP guide](platform/scp/README.md).

The [Pluton CLI](platform/pluton/pluton-info.py) reads driver status by default;
with transport enabled it can query protocol versions, services and running
firmware metadata. For example, as an administrator:

```sh
python3 platform/pluton/pluton-info.py --versions --services --device-info
```

See the [PCBI interface](platform/pluton/protocol.md) for its restricted query
API. TPM applications instead use the separate TPM 2.0 device and standard
TPM2 userspace tools.

### Suspend and resume

The Linux 7.3 series adds coordinated N1X s2idle; physical results exist for
20-CPU BIOS 303 and 305 systems. Inspect the selected sleep mode with
`cat /sys/power/mem_sleep` and follow the [sleep setup/recovery guide](improvements/kernel/README.md#suspend-and-recovery).
The [validation record](improvements/VALIDATION.md) lists tested device recovery,
sleep energy and remaining gaps, including RTC timed wake. Those results do not
qualify sleep with experimental DSP firmware published.

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

## Acknowledgements

A big thank-you to **Josephine Pfeiffer**, **Jordi Ibáñez** and
**Sean Kenneth Doherty** for helping improve Linux support on the ProArt P16.
Your contributions and shared experience are much appreciated!

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
