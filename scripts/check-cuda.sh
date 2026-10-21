#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
check_machine
nvcc=/opt/cuda/bin/nvcc
"$nvcc" --version
mkdir -p "$REPO/build/cuda"
"$nvcc" -O2 -std=c++17 -arch=sm_121 "$REPO/cuda/vector-add.cu" -o "$REPO/build/cuda/vector-add"
"$REPO/build/cuda/vector-add"
