#!/usr/bin/env bash
# Extend the already audited P16 ACPI and service policy to the npu2 kernel.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
repo=$(cd "$(dirname "$0")/.." && pwd)
install -Dm644 "$repo/config/p16-acpi" /etc/initcpio/install/p16-acpi
install -Dm644 "$repo/config/zz-p16-hardware-fixes.conf" /etc/mkinitcpio.conf.d/zz-p16-hardware-fixes.conf
install -Dm644 "$repo/config/p16-asus-controls.service" /etc/systemd/system/p16-asus-controls.service
install -Dm644 "$repo/config/p16-charge-limit.service" /etc/systemd/system/p16-charge-limit.service
systemctl daemon-reload
echo 'P16 npu2 ACPI and service policy installed; existing UKIs unchanged.'
