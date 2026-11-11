#!/usr/bin/env bash
# Fetch the reviewed driver source without running downloaded code as root.
source "$(dirname "$0")/common.sh"
check_arch
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
# Keep the pinned upstream tree plus exactly the maintained platform patch.
python3 - "$REPO" "$target" <<'PATCH_CHECK'
from pathlib import Path
import subprocess
import sys
root, target = map(Path, sys.argv[1:])
patch = root / 'platform/hwmon/n1x-platform.patch'
expected = patch.read_bytes()
actual = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=target)
if not actual:
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=target).strip():
        raise SystemExit('Preserving unexpected hwmon worktree changes')
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=target, check=True)
    subprocess.run(['git', 'apply', '--intent-to-add', str(patch)], cwd=target, check=True)
    actual = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=target)
if actual != expected:
    raise SystemExit('Preserving hwmon changes that differ from the maintained patch')
PATCH_CHECK
printf 'Pinned source ready: %s\nAfter booting the P16 kernel: sudo %q/scripts/install-dkms.sh\n' "$commit" "$target"
