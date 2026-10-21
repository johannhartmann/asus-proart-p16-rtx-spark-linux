#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
require_root
check_machine
mountpoint -q /boot || { echo '/boot muss eingehängt sein.' >&2; exit 1; }
[[ $(findmnt -n -o FSTYPE /boot) == vfat ]] || { echo 'FAT-EFI-Partition unter /boot erforderlich.' >&2; exit 1; }
[[ -f /boot/limine.conf ]]
[[ ! -e /usr/lib/modules/$RELEASE && ! -e /boot/EFI/Linux/omarchy_linux-p16-asus.efi ]] || {
  echo 'P16-Kernel ist bereits vorhanden; bestehende Installation wird nicht überschrieben.' >&2; exit 1;
}
packages=("$REPO/kernel/linux-p16-asus-7.2.8-14-aarch64.pkg.tar.zst" "$REPO/kernel/linux-p16-asus-headers-7.2.8-14-aarch64.pkg.tar.zst")
for pkg in "${packages[@]}"; do [[ -s $pkg ]] || { echo "Paket fehlt: $pkg" >&2; exit 1; }; done
python3 - "$REPO" <<'PY'
from pathlib import Path
import hashlib, sys
root = Path(sys.argv[1]) / 'build/acpi/kernel/firmware/acpi'
for name, pin in {'DSDT.aml':'80e0ad4a051704003d09029cb600a9814e1cd370ce774b9749dc09d2232b5aaf', 'SSDT.aml':'9b28ffc14c19f8b7ea2278de88ff9ec070f5f70401107d81fef067a916aa9695'}.items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest() == pin, name
PY
# Back up configuration and fingerprint all existing UKIs before any writes.
backup=$(mktemp -d /root/p16-install.XXXXXXXX)
export P16_BACKUP="$backup"
python3 - <<'PY'
from pathlib import Path
import hashlib,json,os,shutil
backup=Path(os.environ['P16_BACKUP'])
paths=['/boot/limine.conf','/etc/initcpio/install/p16-acpi','/etc/mkinitcpio.conf.d/zz-p16-hardware-fixes.conf','/etc/mkinitcpio.conf.d/zz-p16-keyboard.conf','/etc/mkinitcpio.conf.d/zz-p16-input.conf','/etc/limine-entry-tool.d/zz-p16-keyboard.conf','/etc/systemd/system/p16-asus-controls.service','/etc/systemd/system/p16-charge-limit.service','/etc/systemd/system/power-profiles-daemon.service.d/20-p16-asus.conf','/usr/local/libexec/p16-charge-limit','/usr/local/bin/p16-temperatures','/etc/initcpio/p16-acpi/DSDT.aml','/etc/initcpio/p16-acpi/SSDT.aml']
for name in paths:
    path=Path(name)
    if path.exists():
        target=backup/name.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
(backup/'files.json').write_text(json.dumps({name:Path(name).exists() for name in paths},indent=2))
(backup/'efi-hashes.json').write_text(json.dumps({str(p):hashlib.blake2b(p.read_bytes()).hexdigest() for p in Path('/boot/EFI/Linux').glob('*.efi')},indent=2))
PY
# Only this transaction suppresses existing package hooks. DKMS, depmod and
# creation of the single additional UKI are performed explicitly below.
hooks=$(mktemp -d /run/p16-hooks.XXXXXXXX)
trap 'rm -rf "$hooks"' EXIT
for directory in /usr/share/libalpm/hooks /etc/pacman.d/hooks; do
  for hook in "$directory"/*.hook; do
    if [[ -e $hook ]]; then ln -sf /dev/null "$hooks/${hook##*/}"; fi
  done
done
pacman -U --noconfirm --hookdir "$hooks" "${packages[@]}"
dkms autoinstall -k "$RELEASE"
depmod -a "$RELEASE"
install -Dm644 "$REPO/config/p16-acpi" /etc/initcpio/install/p16-acpi
install -Dm644 "$REPO/config/zz-p16-hardware-fixes.conf" /etc/mkinitcpio.conf.d/zz-p16-hardware-fixes.conf
install -Dm644 "$REPO/config/zz-p16-keyboard.conf" /etc/mkinitcpio.conf.d/zz-p16-keyboard.conf
install -Dm644 "$REPO/config/limine-p16-keyboard.conf" /etc/limine-entry-tool.d/zz-p16-keyboard.conf
install -Dm644 "$REPO/config/zz-p16-input.conf" /etc/mkinitcpio.conf.d/zz-p16-input.conf
for table in DSDT.aml SSDT.aml; do
  install -Dm644 "$REPO/build/acpi/kernel/firmware/acpi/$table" "/etc/initcpio/p16-acpi/$table"
done
install -Dm755 "$REPO/scripts/p16-charge-limit" /usr/local/libexec/p16-charge-limit
install -Dm755 "$REPO/scripts/p16-temperatures" /usr/local/bin/p16-temperatures
for unit in p16-asus-controls.service p16-charge-limit.service; do
  install -Dm644 "$REPO/config/$unit" "/etc/systemd/system/$unit"
done
install -Dm644 "$REPO/config/20-p16-asus.conf" /etc/systemd/system/power-profiles-daemon.service.d/20-p16-asus.conf
# Build a host-specific command line. Never distribute root/LUKS UUIDs.
python3 - "$REPO/build/p16.cmdline" <<'PY'
from pathlib import Path
import shlex,sys
args=shlex.split(Path('/proc/cmdline').read_text())
assert any(a.startswith(('root=','rd.luks.name=','cryptdevice=')) for a in args), 'Vom installierten System starten, nicht vom Live-ISO'
blocked=('BOOT_IMAGE=', 'initrd=', 'acpi_osi=', 'console=', 'acpi=', 'systemd.unit=', 'rd.driver.blacklist=', 'module_blacklist=', 'modprobe.blacklist=')
args=[a for a in args if not a.startswith(blocked)]
def quote(a):
    assert '"' not in a and '\n' not in a
    return '"'+a+'"' if any(c.isspace() for c in a) else a
Path(sys.argv[1]).write_text(' '.join(map(quote,args))+' console=tty0 acpi=nospcr acpi_osi="!Windows 2022"\n')
PY
mkinitcpio --kernel "$RELEASE" --cmdline "$REPO/build/p16.cmdline" --uki "$REPO/build/linux-p16-asus.efi"
python3 "$REPO/scripts/verify-boot.py" --image "$REPO/build/linux-p16-asus.efi" --image-only
limine-entry-tool --no-hooks --add-uki linux-p16-asus "$REPO/build/linux-p16-asus.efi" --comment 'ASUS ProArt P16: ACPI, SPI HID, ARM64 WMI'
python3 - <<'PY'
from pathlib import Path
import hashlib,json,os,re
backup=Path(os.environ['P16_BACKUP'])
p=Path('/boot/limine.conf');text=p.read_text()
for key,value in [('quiet','no'),('timeout','10')]:
    pattern=rf'^{key}:.*$'
    text=re.sub(pattern,f'{key}: {value}',text,flags=re.M) if re.search(pattern,text,re.M) else f'{key}: {value}\n'+text
# Keep the boot default from the initial config.
before=(backup/'boot/limine.conf').read_text()
assert re.findall(r'^default_entry:.*$',before,re.M)==re.findall(r'^default_entry:.*$',text,re.M), 'Bootstandard wurde geändert'
p.write_text(text)
for name,pin in json.loads((backup/'efi-hashes.json').read_text()).items():
    assert hashlib.blake2b(Path(name).read_bytes()).hexdigest()==pin, 'Bestehendes EFI-Image verändert: '+name
PY
python3 "$REPO/scripts/verify-boot.py"
systemctl daemon-reload
systemctl enable p16-charge-limit.service
pacman -Qk linux-p16-asus linux-p16-asus-headers
sync
printf 'Installation abgeschlossen. Sicherung: %s\nBeim nächsten Start linux-p16-asus im Limine-Menü auswählen.\n' "$backup"
