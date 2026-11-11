# P16 hardware support

These additions target H7607BA/N1X ARM64, with physical evidence on BIOS 303
and 305. See the validation record for the scope and limits of each test.

1. Read [validation and limits](VALIDATION.md) and identify the exact hardware.
2. Prepare [Linux 7.3 and the ordered kernel patches](kernel/README.md).
3. Add the [audio route fix and userspace setup](audio/README.md) as needed.
4. Build/package/install with the distribution's normal procedure, preserving
   a working kernel entry and matching GPU modules, firmware and initramfs.
5. Add [telemetry](telemetry/README.md), load the platform modules, and check
   sensors, profiles, battery threshold, audio and suspend on the target device.

The kernel guide includes all N1X and SPI-HID prerequisites for this exact
series, including work from NVIDIA and the reference distro. The patches are
source inputs for distribution maintainers and advanced users; there is no
personal package service or automatic build/update integration here.

Battery control is exposed without forcing a threshold. Fan RPM reporting does
not replace the firmware's thermal policy. Desktop application shortcuts remain
for the user to choose. Standard GPU, CUDA and container packages remain the
responsibility of their respective distributions/vendors. The GPU has CUDA
compute capability 12.1; select a toolkit that supports it.

The kernel series also includes the upstream MT7925 MLO membership correction;
it preserves automatic band/AP selection and 6 GHz availability.

The base patches are also available for review in [kernel PR1958](https://github.com/omacom/omarchy-pkgs/pull/1958).

Run `python3 improvements/verify.py` from the repository root to check the
exported source hashes. The kernel and telemetry guides describe the function
tests. [sources.json](sources.json) records exact provenance; `SHA256SUMS` covers
the files in this directory, excluding itself.
