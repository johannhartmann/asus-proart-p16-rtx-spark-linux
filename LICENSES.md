# Licensing

- `acpi/acpi_builder.py` and `acpi/power-*`: MIT, copyright Josephine Pfeiffer. The full license is in `acpi/LICENSE`; provenance and the upstream commit are recorded in `sources.json`.
- `acpi/acpica-unix-20260408.tar.gz`: unmodified ACPICA source release. Its license texts and copyright notices are included in the archive.
- `kernel/`: Linux patches and kernel recipe under their respective source notices and the PKGBUILD's GPL-2.0-only license designation. The recipe downloads and verifies the Linux source release; its `COPYING` and `LICENSES/` apply to the resulting kernel. Upstream author and Signed-off-by notices are preserved.
- New installation scripts, `scripts/p16-temperatures`, `scripts/p16-charge-limit`, `cuda/vector-add.cu`, configuration files, tests and documentation in this repository: MIT; see `licenses/MIT.txt`.

Machine firmware dumps, generated EFI images, kernel packages, passwords, private keys and machine-specific UUIDs are excluded from this repository.
