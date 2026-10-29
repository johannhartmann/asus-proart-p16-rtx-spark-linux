#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
repo=$(cd "$(dirname "$0")/.." && pwd)
install -Dm755 "$repo/scripts/p16-boot-menu-policy.py" /usr/local/sbin/p16-boot-menu-policy
install -Dm644 "$repo/config/zz-p16-boot-menu.hook" /etc/pacman.d/hooks/zz-p16-boot-menu.hook
python3 /usr/local/sbin/p16-boot-menu-policy
