# Kernel38 staged as an additional boot entry

The [offline-qualified kernel38 bundle](kernel38-offline-20261118.md) is
installed on the ASUS ProArt P16 H7607BA as `linux-p16-platform-38`, its
matching headers, and `linux-p16-platform-38-drivers`, all version `7.2.8-38`.
The [staging receipt](kernel38-staged-20261118.json) records package hashes,
the 13 installed production-module hashes and the Limine UKI pin.

The generic DKMS post-transaction hook initially replaced the package-owned
`hid-sensor-als.ko`, `spi-hid.ko`, `spi-hid-acpi.ko` and `spbm.ko`. Reinstalling
the exact 615.78.08 driver package after that hook restored all 13 candidate
hashes; `pacman -Qkk` reports zero altered driver or header files. Only the
kernel38 UKI was rebuilt afterward, so its embedded SPI HID modules match
the restored installed modules. The platform image check passed with **8,504
installed** and **430 initramfs** modules carrying valid BTF; it also checked
kernel and NVIDIA versions, module dependencies, ACPI policy and embedded
module bytes.

Limine exposes `Omarchy/linux-p16-platform-38`; its default remains
`Omarchy/linux-p16-platform-36`. The permanent UEFI BootOrder remains
`0002,0001,2001,2002,2003`, with Limine first. Kernel34, kernel36, kernel37
and recovery entries remain available. This is a staged candidate; native
kernel38 boot, camera capture, full warning scan and physical suspend have
not yet been qualified. The running system remains kernel37 and NVIDIA
615.78.08. The signed 620.70.06 alternative was built offline and remains
uninstalled.
