# Kernel 37 staged as an additional boot entry

The [offline-qualified kernel37 bundle](kernel37-offline-20261118.md) was
installed on the ASUS ProArt P16 H7607BA as `linux-p16-platform-37`, matching
headers and `linux-p16-platform-37-drivers`, all version `7.2.8-37`. The
[staging receipt](kernel37-staged-20261118.json) records the three package
SHA256 values, all 13 installed production module hashes, the UKI hash and the
preserved boot-image hashes.

The first kernel/header/driver transaction built a valid kernel37 UKI, but
Arch's generic DKMS post-transaction hook replaced four package-owned modules:
`hid-sensor-als.ko`, `spi-hid.ko`, `spi-hid-acpi.ko` and `spbm.ko`. It left the
other nine candidate modules intact. The exact driver package was reinstalled
after DKMS finished; this time its 13 installed module hashes matched the
offline build manifest and `pacman -Qkk` found zero altered driver files.
The managed kernel37 UKI was then rebuilt to embed the restored SPI HID
modules. The platform image check passed with 8,504 installed and 430
initramfs modules carrying valid BTF; it also checked that embedded SPI HID
bytes equal the installed files.

Limine exposes `Omarchy/linux-p16-platform-37` as a selectable entry. The
default remains `Omarchy/linux-p16-platform-36`; kernel34 and the separate
recovery image retain their documented SHA256 values. The kernel37 UKI SHA256
is `ff6472443b4e5e9f7690135717ae35f1e8a342c45259467b5a2ad2601931a6bc`.
The root-run package integrity check found no content mismatch. Kernel37's
36 reported changes are the known `/boot` FAT mode/time differences on DTBs;
headers and drivers reported zero altered files. `/boot` has about 1.1 GiB
free after staging.

The machine still runs kernel36. Another active `pytest` process was present,
so no reboot was requested. The kernel37 entry is ready for a deliberate
native boot; display/input, audio, NPU, camera, NVENC, Lockdep and physical
suspend/resume have not been qualified on it. A later update that retriggers
generic DKMS must recheck the 13 package-owned module hashes before relying on
the candidate UKI.
