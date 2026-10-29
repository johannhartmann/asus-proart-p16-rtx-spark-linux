#!/usr/bin/env bash
# limine-mkinitcpio-hook owns the /etc hook; NoUpgrade retains our local policy.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
repo=$(cd "$(dirname "$0")/.." && pwd)
config=/etc/pacman.conf
hook=/etc/pacman.d/hooks/90-mkinitcpio-install.hook
install -d -m 0700 /var/lib/p16-platform/boot-hook-backup
[[ -e /var/lib/p16-platform/boot-hook-backup/pacman.conf ]] ||
  cp -a "$config" /var/lib/p16-platform/boot-hook-backup/pacman.conf
[[ -e /var/lib/p16-platform/boot-hook-backup/90-mkinitcpio-install.hook ]] ||
  cp -a "$hook" /var/lib/p16-platform/boot-hook-backup/90-mkinitcpio-install.hook
install -Dm755 "$repo/scripts/p16-mkinitcpio-managed" /usr/local/sbin/p16-mkinitcpio-managed
if ! grep -Eq '^NoUpgrade[[:space:]]*=.*etc/pacman.d/hooks/90-mkinitcpio-install.hook' "$config"; then
  sed -i '/^\[options\]$/a NoUpgrade = etc/pacman.d/hooks/90-mkinitcpio-install.hook' "$config"
fi
install -Dm644 "$repo/config/90-mkinitcpio-install.hook" "$hook"
cmp -s "$repo/config/90-mkinitcpio-install.hook" "$hook"
echo 'P16 mkinitcpio guard installed; experimental UKIs are excluded from broad pacman rebuilds.'
