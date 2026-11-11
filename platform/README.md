# Platform driver matching

The drivers match their hardware interfaces, independently of the computer's
manufacturer, product name and BIOS version. ACPI IDs select supported IP
blocks; resource sizes, firmware ABI versions and protocol bounds are checked
before access. Register offsets, image IDs and supported task graphs describe
the hardware or firmware ABI and remain part of the implementation.

BIOS versions in validation reports describe tested configurations, not an
eligibility allowlist. A new BIOS can work unchanged when those interfaces stay
compatible. Unknown resource layouts or firmware protocols must be rejected
before the affected operation; removing a version restriction does not authorize
guessing a mailbox format, power transition or DMA lifetime.

Source builds, source preparation and the CUDA smoke test require AArch64, not
a BIOS label. Board-specific capture, file-audit and trial tools retain their
P16 model/architecture scope; actual resource, firmware, module, DMA-domain and
readiness checks remain in the drivers and operation-specific preflights.
The historical ACPI byte-splice builder is a separate limitation: it accepts
only its verified table inputs, independently of the BIOS version string.
It cannot transform a different AML layout merely because that BIOS is newer.

- DSP uses the ACPI memory/IRQ resources. Firmware uses the normal firmware
  loader, with a `firmware-name` property override and per-core default names.
  Related devices are located through ACPI companions rather than generated
  platform instance names.
- AFE SRAM size and CPU/VAD/DSP address views come from the existing ASD
  firmware properties. Alignment, address-width and overflow checks apply to
  each view. ALSA buffer limits follow the reported SRAM capacity.
- SCP uses ACPI SRAM and mailbox resources. The implemented log/query ABI is
  checked directly; different firmware ABIs need corresponding protocol support.
- Pluton uses the ACPI register window and stride alias, and checks `_HRV`.
- SPI HID identifies the stream-only MSFW1111 controller by its ACPI ID and
  HID VID/PID. It does not depend on the host system's DMI strings.
- NPU/SROOT uses the GB10/T264 display VBIOS-locator register. Its address is
  part of the SoC register map; the NVDA3000 SVP resource does not describe it.
  Firmware staging uses the loaded image size. The host checks signed-container
  structure and section bounds; SROOT authenticates its certificate/signatures.
  Firmware package checksums remain acquisition checks, outside the driver.
- hwmon selects the supported MT8901 MTEL ABI using firmware `PLID = 2` and the
  advertised MTEL schema. Its fixed SoC register map is not an ASUS board table.
  The maintained patch is applied to the pinned hwmon source by
  `scripts/prepare-spark-hwmon.sh`.

These changes do not establish hardware qualification on other computers.
Published DSP memory still requires a verified quiesce/shutdown contract before
release. No running module is replaced by preparing or testing these sources.

## Build integration

For an external build of DSP, SCP and Pluton:

```sh
make -C platform KDIR=/path/to/kernel/build W=1 -j2
```

For in-tree integration, place this directory under `drivers/platform/n1x`,
source `drivers/platform/n1x/Kconfig` from `drivers/platform/Kconfig`, and add
`obj-y += n1x/` to `drivers/platform/Makefile`. Select `CONFIG_N1X_ADSP`,
`CONFIG_N1X_SCP` and `CONFIG_N1X_PLUTON` as needed. The source still requires the
matching MediaTek power, AFE and SROOT interfaces described by each driver.
Leaf Kbuilds also support their DKMS packages directly.

Native protocol tests require no hardware. From the integrated Linux tree:

```sh
python3 tools/testing/kunit/kunit.py run --arch=arm64 \
  --kunitconfig=drivers/platform/n1x/tests/.kunitconfig \
  n1x-platform-protocol
```

Install QEMU's ARM64 system emulator to execute that configuration. The suite
checks DSP IPC, PCM descriptors, PCBI replies and signed firmware envelopes.
It complements the actual-function fault/concurrency harnesses in this
repository; it does not boot platform firmware or qualify hardware.

The aggregate `drivers/platform/n1x` placement above is a local build/test
integration, not a proposed upstream subsystem layout. See
[kernel driver architecture](../docs/kernel-driver-architecture.md) for
subsystem ownership, ABI contracts, validation and remaining blockers.

Run the offline regression suite without kernel headers:

```sh
bash scripts/check-kernel-drivers.sh
```

To also build all maintained modules and test the separate hwmon/NPU sources:

```sh
bash scripts/check-kernel-drivers.sh --build \
  /usr/lib/modules/$(uname -r)/build \
  "$PWD/build/spark_hwmon" "$PWD/../n1x-lab/npu"
```

This command does not install or load modules. `W=1` builds and host-side
ASan/UBSan tests supplement hardware qualification; they do not establish
working suspend, recovery, reload or support on a different board.
