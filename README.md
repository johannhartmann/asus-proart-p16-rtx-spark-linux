# Omarchy Nightly auf dem ASUS ProArt P16 RTX Spark

Installationsanleitung für **ASUS ProArt P16 H7607BA**, NVIDIA RTX Spark **N1X / AArch64**, BIOS **H7607BA.300**, EC **2.16**. Diese Dateien sind für das ARM-Modell bestimmt; sie passen nicht zu den AMD-/Intel-P16-Modellen.

Die Installation besteht aus dem offiziellen ARM64-Nightly und einem separat paketierten P16-Kernel. Das Kernelrezept ist auf Omarchy **7.2.8-14** festgelegt und erzeugt **7.2.8-14-omarchy-p16-asus**. Ein neueres Nightly kann einen neueren Standardkernel enthalten; der zusätzliche P16-Kernel wird daneben installiert. Die Patches nicht auf einen beliebigen neueren Kernel anwenden.

Enthalten sind die Quellen und Buildrezepte für Tastatur/Touchpad, ACPI-/Akku-Korrekturen, SPI-HID, ASUS-Steuerung, Temperaturanzeige sowie ein CUDA-Funktionstest. Linux wird beim Build von kernel.org heruntergeladen und anhand der Prüfsummen und Signaturen des enthaltenen Omarchy-Rezepts geprüft. Firmwaretabellen werden auf dem Zielrechner ausgelesen und daraus erzeugt.

## 1. ARM64-Nightly installieren

Benötigt werden ein USB-Stick mit mindestens 8 GB, eine USB-Tastatur für die Ersteinrichtung und Netzteil/Internet. Secure Boot im UEFI ausschalten. Die Installation auf ein Laufwerk löscht dessen Daten, wenn die vollständige Laufwerksinstallation gewählt wird.

Aktuelles ARM64-Nightly herunterladen und prüfen:

```bash
python3 scripts/download-nightly.py
```

Das Skript verwendet ausschließlich das [ARM64-Nightly-Manifest](https://nightly.omarchy.org/edge-aarch64/latest.json), prüft Architektur, Dateigröße und SHA-256 und speichert ISO und Manifest unter `build/iso/`. Das allgemeine `edge/latest.json` verweist auf das x86_64-Image.

ISO mit einem Image-Schreibprogramm auf den USB-Stick schreiben. Vom Stick über das UEFI-Bootmenü starten und Omarchy installieren. Im Installer deutsche Tastatur wählen. Für den P16 muss die Linux-Kommandozeile diese Parameter enthalten:

```text
console=tty0 acpi=nospcr acpi_osi="!Windows 2022"
```

`console=tty0 acpi=nospcr` gehört zur Omarchy-N1X-Konfiguration. `acpi_osi="!Windows 2022"` sorgt auf diesem BIOS für die SSPM-/I²C-Erkennung und damit für interne Tastatur und Touchpad. Falls die interne Eingabe im Installer fehlt, die USB-Tastatur verwenden; der zusätzliche P16-Kernel erhält die Einstellung in Schritt 5 dauerhaft.

Nach der Installation vom internen Laufwerk in die normale Omarchy-Sitzung starten. Alle folgenden Befehle aus dem Wurzelverzeichnis dieses Repositorys ausführen. `sudo` nur bei den ausdrücklich gekennzeichneten Schritten verwenden.

## 2. Buildwerkzeuge und Plattformpakete

```bash
omarchy pkg add base-devel bc cpio gettext libelf pahole python git gnupg clang llvm lld rust rust-bindgen rust-src xxhash zstd
omarchy pkg add nvidia-open-dkms nvidia-utils python-gobject
```

Das Nightly richtet die N1X-Plattform einschließlich NVIDIA-Grafik, verschlüsseltem Start und Limine ein. Keine x86_64-NVIDIA-Pakete oder NVIDIA-`.run`-Installer verwenden.

Für CPU-Energieprofile wird Omarchys NVIDIA-fähiger Daemon benötigt:

```bash
sudo pacman -S --needed omarchy-power-profiles-daemon
sudo systemctl enable power-profiles-daemon.service
```

Falls Pacman nach dem Austausch von `power-profiles-daemon` fragt, den Austausch bestätigen. Das Omarchy-Paket stellt denselben Dienst und `powerprofilesctl` bereit.

## 3. ACPI-Dateien erzeugen

Die Originaltabellen vom normalen Nightly-Kernel auslesen, **bevor** ein Kernel mit ACPI-Overrides gestartet wird:

```bash
sudo ./scripts/dump-acpi.sh
python3 scripts/build-acpi.py
```

Der Build verwendet das enthaltene ACPICA **20260408** und prüft die Originaltabellen sowie beide erzeugten Tabellen per SHA-256. Andere BIOS-Versionen oder bereits gepatchte Tabellen werden abgewiesen. Ein bereits vorhandenes `build/firmware/` wird nicht überschrieben.

Ausgaben:

```text
build/acpi/kernel/firmware/acpi/DSDT.aml
build/acpi/kernel/firmware/acpi/SSDT.aml
build/acpi/manifest.json
```

Die DSDT aktiviert die korrekte SSPM-Erkennung; die SSDT korrigiert die EC-/Akku-Methoden. Der Kernel enthält dazu den erforderlichen ARM64-Allocator-Patch. Die ACPI-Dateien ausschließlich über den mitgelieferten Hook in den zusätzlichen P16-Kernel einbinden. Es wird kein BIOS geflasht.

## 4. P16-Kernel bauen

Als normaler Benutzer:

```bash
./scripts/build-kernel.sh
```

Die erste Ausführung lädt die Linux-Quellen. Die Signaturprüfung bleibt eingeschaltet; ein separates GPG-Verzeichnis liegt unter `build/gnupg/`. Der Build benötigt mehrere zehn GB freien Platz und erzeugt:

```text
kernel/linux-p16-asus-7.2.8-14-aarch64.pkg.tar.zst
kernel/linux-p16-asus-headers-7.2.8-14-aarch64.pkg.tar.zst
```

Das Headerpaket ist für NVIDIA-DKMS erforderlich. Kernel und Module werden durch Pacman verwaltet. Der Buildbaum wird nach der Installation nicht als Modul-/Headerquelle benötigt.

Die Patchreihenfolge und SHA-256-/BLAKE2-Prüfsummen stehen vollständig in `kernel/PKGBUILD`. Der kombinierte ASUS-Patch enthält bereits die ARM64-WMI-Portierung, die Verschiebung nach `drivers/platform/asus/` und die modellspezifische RSOC-Korrektur. Diese Änderungen nicht ein zweites Mal anwenden.

## 5. Kernel und Systemdateien installieren

Vom installierten Omarchy aus:

```bash
sudo ./scripts/install-kernel.sh
```

Das Skript:

- prüft AArch64, Modell, BIOS, EFI-Mount und ACPI-Dateien;
- sichert die betroffenen Konfigurationen unter `/root/p16-install.<Kennung>/`;
- installiert Kernel und Header, baut NVIDIA-DKMS und erzeugt die Modulabhängigkeiten;
- installiert die frühen Eingabetreiber, den begrenzten ACPI-Hook und die ASUS-Dienste;
- übernimmt die Root-/LUKS-Parameter des Zielrechners und ergänzt die P16-Kerneloptionen;
- baut einen zusätzlichen UKI und prüft Kernelinhalt, ACPI-Tabellen und benötigte Module;
- legt den Limine-Eintrag `linux-p16-asus` an und prüft die BLAKE2b-Hashes;
- zeigt das Bootmenü zehn Sekunden an und erhält den vorhandenen Standard-Eintrag.

Vorhandene EFI-Images werden nicht neu gebaut. Eine bereits installierte P16-Kernelversion wird nicht überschrieben. Wenn ein Schritt fehlschlägt, den Fehler vor einem Neustart beheben; die Sicherung liegt im oben genannten Verzeichnis.

Neustarten und **`linux-p16-asus`** im sichtbaren Limine-Menü auswählen. Danach prüfen:

```bash
uname -r
./scripts/check-system.sh
sudo python3 scripts/verify-boot.py
```

`uname -r` muss `7.2.8-14-omarchy-p16-asus` melden. Der Akku muss plausible Werte liefern, NVIDIA muss in `nvidia-smi` erscheinen und die drei Dienste müssen erfolgreich gestartet sein. `powerprofilesctl list` soll `nvidia_rtx_spark` und `platform_profile` als Treiber melden.

## 6. Deutsche Tastatur

In der angemeldeten grafischen Sitzung als normaler Benutzer:

```bash
python3 scripts/set-german-keyboard.py
sudo localectl --no-convert set-keymap de
```

Das Skript verwendet Omarchys installierte Tastaturlogik, setzt Desktop und Fcitx gemeinsam auf `de` und lädt Hyprland neu. Es schreibt nicht in `/usr/share/omarchy/`. `hid_asus` wird im initramfs vor der I²C-HID-Erkennung geladen, damit die interne Tastatur auch am LUKS-Prompt verfügbar ist.

## 7. ASUS-Profile, Akku und Temperaturen

```bash
powerprofilesctl set balanced
powerprofilesctl set performance
powerprofilesctl set power-saver
```

Die Zuordnung lautet Balanced → ASUS Balanced, Performance → ASUS Performance, Power Saver → ASUS Quiet. Der Daemon steuert daneben das NVIDIA-CPU-Backend.

`p16-asus-controls.service` lädt den ASUS-Treiber vor der Profilerkennung. `p16-charge-limit.service` setzt nach der Registrierung des Akkus ein Ladelimit von **100 %**. Beide Dienste sind auf den enthaltenen Kernelrelease begrenzt. Die Hersteller-Lüfterkurven bleiben aktiv.

Temperaturen anzeigen:

```bash
p16-temperatures
p16-temperatures --watch
p16-temperatures --json
```

Die Anzeige liest ACPI-, NVIDIA-, NVMe-, WLAN- und Lüfterschnittstellen. PSYS/PSOC werden durch den Kernelpatch von echten Temperaturzonen getrennt. Acht Firmwarezonen enthalten ungültige `_CRT`-Grenzen (`0x7fffffff`); ihre Temperaturmessungen sind nutzbar, aber es werden keine Ersatzgrenzen erfunden. Die vorhandenen THRM-Grenzen von 100 °C passiv und 103 °C kritisch bleiben erhalten.

## 8. CUDA und GPU-Container

```bash
omarchy pkg add cuda
source /etc/profile
nvcc --version
./scripts/check-cuda.sh
```

Das Toolkit liegt unter `/opt/cuda`. Der Test kompiliert für **`sm_121`** und kontrolliert 4096 Ergebnisse einer Vektoraddition auf der GPU. Bei Erfolg erscheint `"result":"passed"`. NVIDIA-SMIs CUDA-Anzeige beschreibt die Treiberfähigkeit; `nvcc --version` zeigt die installierte Toolkit-Version. Für vorgefertigte PyTorch-Wheels gilt zusätzlich deren eigene CUDA-Runtime-Version.

Für Docker-GPU-Zugriff:

```bash
omarchy install docker
omarchy pkg add nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker --set-as-default
sudo systemctl restart docker
```

Container anschließend mit `docker run --gpus all ...` starten. Ein Docker-Neustart unterbricht laufende Container. Python-/Trainingsprojekte und Kubernetes sind unabhängig von den Hardwareanpassungen einzurichten.

## 9. Boot-Reparatur und Updates

Bei einem fehlgeschlagenen P16-Start im Limine-Menü den vorhandenen `linux-omarchy`-Eintrag wählen. Bei schwarzem Bildschirm `linux-omarchy-fallback` verwenden. `Esc` blendet ein durch andere Einstellungen verstecktes Bootmenü ein. Auf dem Standardkernel werden die P16-ACPI-Overrides und die beiden P16-Dienste nicht aktiviert.

Bei einer BLAKE2b-Meldung das betroffene EFI-Image und den Eintrag wieder gemeinsam aus derselben Sicherung herstellen oder mit `limine-entry-tool` neu registrieren. Keine EFI-Datei nach der Registrierung verändern. PE-Sektionen ausschließlich lesend untersuchen; `scripts/verify-boot.py` verändert keine Images.

Nach NVIDIA-Paketupdates muss DKMS auch für den P16-Kernel erfolgreich bauen:

```bash
dkms status
sudo dkms autoinstall -k 7.2.8-14-omarchy-p16-asus
sudo depmod -a 7.2.8-14-omarchy-p16-asus
```

Anschließend den UKI über Omarchys regulären `limine-mkinitcpio`-Ablauf erneuern und `sudo python3 scripts/verify-boot.py` ausführen, damit Treiber im initramfs und im Root-Dateisystem übereinstimmen. Vor Kerneländerungen den Standardkernel und dessen Fallback-Eintrag erhalten.

Bei einem BIOS-Update die alten ACPI-Overrides nicht übernehmen. Für einen anderen Kernelrelease müssen Patches, mkinitcpio-Hook, Drop-in und `ConditionKernelVersion` der Dienste gemeinsam angepasst und geprüft werden.

## Hardware und Grenzen

| Hardware | Identität |
|---|---|
| GPU | NVIDIA `10de:2e03`, Subsystem `1043:1484`, Compute Capability 12.1 |
| Interne Tastatur | HID `0b05:4b42`, ACPI `MKB0001`, `hid_asus` |
| Touchpad | HID `093a:4f01`, `hid-multitouch` |
| SPI-Sensorhub | `MSFW1111` / `PNP0C51`, virtueller GPIO/IRQ 190, `spi_hid_acpi` |
| ASUS-WMI | Management `97845ED0-4E6D-11DE-8A39-0800200C9A66`, Event `0B3CBB35-E3C2-45ED-91C2-4C5A6D195D1C` |

SPI-HID transportiert den Sensorhub; die Vollständigkeit der Sensormessungen, physischer Ladestopp, Lüfterreaktionen, Suspend/Resume, NVENC/NVDEC und thermische Abschaltung sind durch diese Installation nicht automatisch nachgewiesen. ASUS Armoury und eigene Lüfterkurven werden nicht aktiviert. Optionale NVML-Leistungs-/Speicheranzeigen können auf N1X fehlen.

## Dateistruktur und Quellen

```text
kernel/       vollständiges Omarchy-Kernelrezept, Konfiguration, Signaturen, P16-Patches
acpi/         ACPI-Builder, Transformationsquellen, ACPICA-Quellarchiv, MIT-Lizenz
config/       mkinitcpio-/Limine-Dateien und systemd-Dienste
scripts/      Build, Installation, Tastatur, Temperaturanzeige und Prüfungen
cuda/         CUDA-C++-Testprogramm
sources.json  Herkunft und feste Upstream-Commits
SHA256SUMS    Prüfsummen der Repository-Dateien
build/        lokale Downloads und Buildausgaben; nicht versioniert
```

- [Omarchy ARM64-/N1X-Installation](https://github.com/omacom/omarchy-iso/blob/quattro/N1X.md)
- [Nightly-Build und ARM64-Publikation](https://github.com/omacom/omarchy-iso/blob/quattro/.github/workflows/nightly-build.yml)
- [Omarchy-Kernelrezept](https://github.com/omacom/omarchy-pkgs/tree/a8f9d7512a7fe61561c9fba908545f70ff631ede/pkgbuilds/linux-omarchy-aarch64)
- [P16-ACPI-Quellen](https://github.com/pfeifferj/archlinuxarm-proart-p16/tree/3484cc008a9ee00b34c086c729e28e935cbc3430)
- [SPI-HID v5](https://lore.kernel.org/all/20261009-send-upstream-v5-0-384af01da3ee@chromium.org/)

Prüfsummen prüfen: `sha256sum -c SHA256SUMS`. Lizenzzuordnung: [LICENSES.md](LICENSES.md).
