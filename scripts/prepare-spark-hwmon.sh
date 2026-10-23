#!/usr/bin/env bash
# Fetch the reviewed driver source without running downloaded code as root.
source "$(dirname "$0")/common.sh"
check_machine
[[ $EUID != 0 ]] || { echo 'Run as your regular user.' >&2; exit 1; }
mapfile -t source_info < <(python3 - "$REPO/sources.json" <<'PY'
import json,sys
source=json.load(open(sys.argv[1]))['spark_hwmon']
print(source['repository'])
print(source['commit'])
PY
)
url=${source_info[0]}
commit=${source_info[1]}
[[ $commit =~ ^[a-f0-9]{40}$ ]]
target=$REPO/build/spark_hwmon
if [[ ! -e $target ]]; then
  mkdir -p "$REPO/build"
  staging=$(mktemp -d "$REPO/build/spark-hwmon.XXXXXXXX")
  trap 'rm -rf "$staging"' EXIT
  git clone --no-checkout "$url" "$staging/source"
  git -C "$staging/source" checkout --detach "$commit"
  mv "$staging/source" "$target"
fi
[[ $(git -C "$target" rev-parse HEAD) == "$commit" ]] || {
  echo 'Existing build/spark_hwmon has a different commit; preserve or move it first.' >&2; exit 1;
}
[[ -z $(git -C "$target" status --porcelain) ]] || {
  echo 'Existing build/spark_hwmon has local changes; preserve or move it first.' >&2; exit 1;
}
printf 'Pinned source ready: %s\nAfter booting the P16 kernel: sudo %q/scripts/install-dkms.sh\n' "$commit" "$target"
