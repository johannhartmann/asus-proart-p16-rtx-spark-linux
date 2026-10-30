#!/usr/bin/env bash
# Extend the audited P16 host integration to the RTX Spark NPU kernel.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
repo=$(cd "$(dirname "$0")/.." && pwd)
install -Dm644 "$repo/config/p16-acpi" /etc/initcpio/install/p16-acpi
install -Dm644 "$repo/config/zz-p16-hardware-fixes.conf" /etc/mkinitcpio.conf.d/zz-p16-hardware-fixes.conf
install -Dm644 "$repo/config/p16-asus-controls.service" /etc/systemd/system/p16-asus-controls.service
install -Dm644 "$repo/config/p16-charge-limit.service" /etc/systemd/system/p16-charge-limit.service
install -Dm755 "$repo/scripts/p16-mkinitcpio-managed" /usr/local/sbin/p16-mkinitcpio-managed
install -Dm755 "$repo/scripts/p16-boot-menu-policy.py" /usr/local/sbin/p16-boot-menu-policy
install -Dm644 "$repo/config/zz-p16-boot-menu.hook" /etc/pacman.d/hooks/zz-p16-boot-menu.hook
systemctl daemon-reload
python3 /usr/local/sbin/p16-boot-menu-policy
echo 'P16 host policy for the RTX Spark NPU kernel installed; UKIs unchanged.'
