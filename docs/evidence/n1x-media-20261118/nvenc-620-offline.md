# NVIDIA 620.70.06 offline driver audit — 18 November 2026

## Scope and provenance

Machine: ASUS ProArt P16 H7607BA, NVIDIA N1X PCI ID `2E03`, running
`7.2.8-36-rtx-spark-npu` with NVIDIA `615.78.08`. NVIDIA's official
[Linux ARM64 archive](https://download.nvidia.com/XFree86/Linux-aarch64/620.70.06/)
and [supported chip list](https://download.nvidia.com/XFree86/Linux-aarch64/620.70.06/README/supportedchips.html)
publish 620.70.06 for this PCI ID. The archive's published SHA256 and the
downloaded `NVIDIA-Linux-aarch64-620.70.06.run` both read
`3fa65a9271e0dde2a4e58c4965c38885a02a3a42accdcb26fc817410607f3e03`.
`bash NVIDIA-Linux-aarch64-620.70.06.run --check` also passed its internal
archive checks. This is a checksum check, not a verified signature.

The `.run` was extracted without installing it. A private copy of its
`kernel-open` tree was patched with the repository's three 615 corrections
using `patch --batch --fuzz=0 -p1`: DRM colorspace deadlock, PM notifier
ownership and UVM PM lock order. All hunks applied. The DRM hunk moved by
117 lines; the PM hunks by 13 or 46 lines; the UVM hunks by one line. Source
compilation therefore passed, but line-offset application alone is not a
semantic or runtime qualification of the patches on 620.

Build command, with no install or module load:

```sh
make -C /home/johann/p16/video-build/driver620/patch-audit/kernel-open -j8 \
  SYSSRC=/usr/lib/modules/7.2.8-36-rtx-spark-npu/build \
  SYSOUT=/usr/lib/modules/7.2.8-36-rtx-spark-npu/build \
  KERNEL_UNAME=7.2.8-36-rtx-spark-npu \
  IGNORE_PREEMPT_RT_PRESENCE=1 modules
```

Exit status: **0**. The [compressed build log](nvenc-620-offline-build.log.gz)
records five completed `.ko` outputs and `MODPOST`. It contains six compiler
warnings: the vendor's unimplemented aarch64 debug breakpoint warning and
five frame-size warnings. It has no compile or modpost error.

| Offline module | SHA256 | `modinfo` version |
| --- | --- | --- |
| `nvidia.ko` | `427cd405e0db5d259b69966f16f43c8d549bd6eb81805ccf3572d711df336ffc` | 620.70.06 |
| `nvidia-modeset.ko` | `b0eb6e8025ec269c197f0eacfd06f905bb07dae2d9179781f0633f458089c44b` | 620.70.06 |
| `nvidia-drm.ko` | `c325bdd5b64e19a599d7e80bb3eb77d16275b0b8d3ea332298dfef6c4745da5d` | 620.70.06 |
| `nvidia-uvm.ko` | `4a642f498459260d1f5d174caf97fe098433cc02ae0ba6e2fce5109262b756c6` | 620.70.06 |
| `nvidia-peermem.ko` | `e574d432513a0fdc7db4c34fc856e8ec018785aef578eaf8d3f89c9c2a6df1bd` | 620.70.06 |

Each module has `7.2.8-36-rtx-spark-npu SMP preempt mod_unload modversions
aarch64` vermagic. The patched file hashes are:

| File under `kernel-open/` | SHA256 |
| --- | --- |
| `nvidia-drm/nvidia-drm-drv.c` | `ac08d551fc96f6635d39c8fbf9e0f826c40ec64df70a9362a29e1ca671e9ed9d` |
| `nvidia/nv.c` | `22a4f8cd97dedeadd6a6e48745e4db4e7ea2f445d3fadaf8db10f765268a38da` |
| `nvidia-uvm/uvm_global.c` | `7a8ec5198dbef15317bff1cd571179644a5c3baeef3a1d2e1cd8eedf0ce0e6f9` |
| `nvidia-uvm/uvm_va_space.h` | `4d482385d5a88b3f2bc781a533c0ce6ca67d644caf8dd93c2e8458c4c606c36f` |

## Runtime boundary and next qualification

`nvidia-smi` and the loaded `nvidia` module still report **615.78.08**. The
installed `nvidia-open-dkms 615.78.08-3`, `nvidia-utils 615.78.08-1`, and
`n1x-nvidia-drm-fix 615.78.08-4` are version-bound. The 620 changelog
contains no explicit claim that N1X NVENC session error 21 is corrected.

The ARM64 distribution's `extra` repository now publishes a matched
`nvidia-utils 620.70.06-1` and `nvidia-open-dkms 620.70.06-1` pair. Both
archives were downloaded to an ignored local build directory and their
detached package signatures verified with the installed Arch Linux ARM
Build System key (`68B3537F39A313B3E574D06777193F152BDBE6A6`, full trust).
Their SHA256 values are respectively
`bc4b8afd35bc14b963b4a2d5d123a76ca72bba3d56c8237ae44b1439ac2bd3da`
and
`e333f8744caa175bccca649b165ff5a31c94de6b7ca573364a0106231351af92`.
The utils archive contains matching `libnvidia-encode.so`, `libnvcuvid.so`,
`nvidia-smi` and versioned firmware. The DKMS package depends on utils
`=620.70.06`. A direct upgrade on the running 615 root is rejected by
versioned dependencies from the kernel34/36/37 driver packages and
`n1x-nvidia-drm-fix`; no 620 package was installed. A separate root and boot
candidate is required for a native comparison while keeping the 615 rollback.
The signed DKMS archive's source was extracted without installing it. All
three local patches applied with fuzz zero, and the four modified file hashes
exactly matched the earlier independently extracted NVIDIA `.run` audit above.

Before a native 620 experiment, make a boot-selectable, fully matched 620
module/userspace/firmware candidate and retain a verified 615 rollback path.
Then check display start, module/firmware identity, physical suspend/resume,
the CUDA and OpenGL NVENC session probes, independently decoded H.264/HEVC/AV1
outputs and real application recording. The offline build establishes none
of those runtime results.

## Matched kernel38 offline build

After the patched kernel38 package completed, the signed distribution DKMS
source with the same three local patches was built through its top-level
Makefile against exact `7.2.8-38-rtx-spark-npu` headers and `vmlinux`. The
first attempt invoking `kernel-open/` directly lacked the generated vendor
core objects; the top-level build generated those objects and finished with
exit 0. All five modules report NVIDIA 620.70.06 and matching kernel38
`vermagic`; all five passed split-BTF validation against the final kernel
BTF. The [receipt](nvenc-620-kernel38-offline.json) pins the module and input
hashes. The [compressed build log](nvenc-620-kernel38-build.log.gz) contains
nine warnings: three unused variables in vendor source, one unimplemented
aarch64 debug-breakpoint warning and five frame-size warnings. There is no
compile or modpost error.

The modules have **not** been loaded or installed. A native test still needs
the signed 620 userspace and firmware in an isolated root/boot candidate and
must preserve a bootable 615 root. The build establishes ABI compatibility
with kernel38, not an NVENC session or display result.

An alternative `linux-p16-platform-38-drivers-nvidia620` package now combines
those five modules with the eight independently qualified P16 platform
modules. Its package SHA256 is
`2f669e17dc68f4f3227c1e9e2a4c54405c8e54c72eeb2bc4d89982cdb77a6232`;
all 13 archived module hashes and the exact `nvidia-utils=620.70.06`
dependency passed package inspection. A separate
[`n1x-nvidia-drm-fix-620`](../../../platform/nvidia/620/README.md) DKMS patch
package (SHA256
`23b3ef76307ab1668a2a6666f081a7e5a52e9f1af25708ffd2d89ab90e10e023`)
pins the three same patches to version 620.70.06. Both packages remain
uninstalled; their build alone does not qualify the 620 runtime.
