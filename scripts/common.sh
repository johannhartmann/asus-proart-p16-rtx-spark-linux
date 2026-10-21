#!/usr/bin/env bash
set -euo pipefail
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE=7.2.8-14-omarchy-p16-asus
check_machine() {
  [[ $(uname -m) == aarch64 ]] || { echo 'AArch64 erforderlich' >&2; exit 1; }
  [[ $(cat /sys/class/dmi/id/sys_vendor) == ASUS &&
     $(cat /sys/class/dmi/id/product_name) == 'ProArt P16 H7607BA' &&
     $(cat /sys/class/dmi/id/bios_version) == H7607BA.300 ]] || {
    echo 'Diese Dateien sind für ASUS ProArt P16 H7607BA mit BIOS H7607BA.300 bestimmt.' >&2; exit 1;
  }
}
require_root() { [[ $EUID == 0 ]] || { echo "Mit sudo ausführen: $0" >&2; exit 1; }; }

# The dump runs as root, but all subsequent compilation runs as the owner.
prepare_build_dir() {
  local build_uid=${SUDO_UID:-$(stat -c %u "$REPO")}
  local build_gid=${SUDO_GID:-$(stat -c %g "$REPO")}
  [[ $build_uid != 0 ]] || { echo 'Repository eines normalen Benutzers verwenden.' >&2; return 1; }
  install -d -m755 -o "$build_uid" -g "$build_gid" "$REPO/build"
}
