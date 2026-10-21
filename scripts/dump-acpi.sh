#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
require_root
check_machine
out="$REPO/build/firmware"
[[ ! -e $out ]] || { echo "$out existiert bereits; zum erneuten Dump umbenennen." >&2; exit 1; }
install -d -m755 "$out"
for table in /sys/firmware/acpi/tables/DSDT /sys/firmware/acpi/tables/SSDT*; do
  [[ -f $table ]] && install -m644 "$table" "$out/${table##*/}"
done
if [[ -n ${SUDO_UID:-} ]]; then chown -R "$SUDO_UID:${SUDO_GID}" "$out"; fi
