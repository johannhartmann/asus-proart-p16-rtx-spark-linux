# Lizenzen

- `acpi/acpi_builder.py`, `acpi/power-*`: MIT, Copyright Josephine Pfeiffer; vollständiger Text in `acpi/LICENSE`. Herkunft und Commit stehen in `sources.json`.
- `acpi/acpica-unix-20260408.tar.gz`: unveränderte ACPICA-Quellveröffentlichung; Lizenztexte und Copyright-Hinweise sind im Archiv enthalten.
- `kernel/`: Linux-Patches und Kernelrezept gemäß den jeweiligen Quellkopfzeilen und dem GPL-2.0-only-Lizenzfeld des PKGBUILD. Die Linux-Quellveröffentlichung wird vom Rezept mit Signatur und Prüfsummen heruntergeladen; deren `COPYING` und `LICENSES/` gelten für den erzeugten Kernel. Autoren-/Signed-off-by-Hinweise in übernommenen Patches bleiben erhalten.
- Die neuen Installationsskripte, `scripts/p16-temperatures`, `scripts/p16-charge-limit`, `cuda/vector-add.cu`, Konfigurationsdateien und Anleitung dieses Repositorys: MIT, siehe `licenses/MIT.txt`.

Die Firmwaretabellen des Rechners, fertige EFI-Images, Kernelpakete, Passwörter, Schlüssel und UUIDs sind nicht Bestandteil dieses Repositorys.
