#!/bin/bash
# Offline checks only: never load modules, access devices, or change boot files.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if (($#)) && [[ $# != 4 || $1 != --build ]]; then
  echo "Usage: $0 [--build KERNEL_BUILD HWMON_SOURCE NPU_SOURCE]" >&2
  exit 2
fi

python3 -m unittest discover -s "$repo/tests" -p test_driver_pm.py -v
python3 -m unittest discover -s "$repo/tests" -p test_hid_series.py -v
python3 -m unittest discover -s "$repo/tests" -p test_kernel_candidate.py -v
for directory in als dsp pluton scp dsp/afe nvidia; do
  for test in "$repo/platform/$directory"/test_*.py; do
    python3 "$test"
  done
done
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
for source in dsp/ipc_test.c dsp/pcm_test.c pluton/protocol_test.c; do
  cc -std=gnu11 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
    "$repo/platform/$source" -o "$temporary/protocol-test"
  "$temporary/protocol-test"
done

if (($#)); then
  kdir=$(realpath -- "$2")
  hwmon=$(realpath -- "$3")
  npu=$(realpath -- "$4")
  [[ -f $kdir/Makefile && -f $hwmon/spbm.c && -f $npu/driver/Kbuild ]]
  make -C "$repo/platform" KDIR="$kdir" W=1 -j2
  for source in "$repo/platform/als" "$repo/platform/sensorhub" "$hwmon" "$npu/driver"; do
    make -C "$kdir" M="$source" W=1 -j2 modules
  done
  python3 -m unittest discover -s "$hwmon/tests" -q
  make -C "$npu" check PYTHON=python3
fi
