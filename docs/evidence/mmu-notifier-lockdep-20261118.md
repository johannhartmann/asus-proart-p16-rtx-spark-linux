# MMU interval notifier Lockdep candidate — 18 November 2026

## Native observation

The running ASUS ProArt P16 H7607BA uses kernel
`7.2.8-36-rtx-spark-npu` and NVIDIA `615.78.08`. Its journal recorded
`WARNING: possible recursive locking detected` on 17 November at 16:47:15
in the NVIDIA UVM non-replayable fault worker. The reported attempted lock
was `(&mm->mmap_lock)` at `mmu_interval_notifier_insert+0x5c`; the same
thread already held that `mmap_lock` for read, a UVM VA-space semaphore and
an HMM block mutex. This boot's Lockdep validation is no longer clean.

The [NVIDIA 615.78.08 source](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/615.78.08/kernel-open/nvidia-uvm/uvm_va_space_mm.c) calls
`__mmu_notifier_register(NULL, mm)` under the mmap write lock when the CUDA
VA space is created. Later HMM block creation can call
`mmu_interval_notifier_insert()` under the mmap read lock. Kernel36's
`mm/mmu_notifier.c` calls `might_lock(&mm->mmap_lock)` before checking whether
the interval notifier tree already exists. On the pre-registered path, the
function does not acquire that lock again; its annotation models a possible
write acquisition that this path does not perform.

The [candidate patch](../../kernel/mmu-interval-notifier-might-lock.patch)
moves `might_lock()` into the branch that actually calls
`mmu_notifier_register()`. It leaves the subscription lookup and registration
condition unchanged. The patch applied to the exact kernel36 source with
zero fuzz, and a private copy built an AArch64 Image successfully. No host
kernel, module, boot entry or driver was changed.

## Isolated EFI/KVM regression

The [kernel model](../../platform/tests/mmu-notifier-lockdep/README.md)
pre-registers the notifier under mmap write lock, inserts an interval under
mmap read lock, removes it and reads `debug_locks`. The same GPL module
(`381585b2eac090963e999cfa74b361831f7f7951fce50f7ff8390909051288a8`)
ran in all three fresh guests. The original Image is the exact
`0eb603b50c077fa1d51e16958ba55f7503f2332daa765ddb8149d72ba1c0b3fa`
kernel36 build; the patched Image is
`d99b5ea47fac45265c39ecc07803eae702f8a0245d426169ef2d27cef8374de6`.
Both report `7.2.8-36-rtx-spark-npu` inside the **guest only**. The source
patch SHA256 is
`7ea8104853bc880a37598967fd3a5f1f1e735d385d1adfa5a85a03a77e4c21ac`.

| Guest | Pre-register / insert lock | Warnings | `debug_locks` | Result |
| --- | --- | ---: | ---: | --- |
| Original Image | Pre-register under write; insert under read | 1, recursive `mmap_lock` | 0 | Expected failure reproduced |
| Patched Image | Same sequence | 0 | 1 | Pass |
| Patched Image | No pre-registration; insert with no mmap lock | 0 | 1 | Registration branch passes |

Exact case metadata and hashes are in [JSON](mmu-notifier-lockdep-20261118.json).
The compressed UART traces are [original](mmu-notifier-lockdep-20261118-original-uart.log.gz),
[patched](mmu-notifier-lockdep-20261118-fixed-uart.log.gz), and
[registration branch](mmu-notifier-lockdep-20261118-fallback-uart.log.gz).
The module insertion returned zero in all cases. The guests did not load a
host module, suspend the host or change its power profile.

## Remaining qualification

This test isolates the warning mechanism. It does not prove that every UVM
fault or MMU-notifier interleaving is correct, nor that the patch fixes every
N1X runtime warning. Build a separately named kernel candidate and all
matching external modules, pass the existing EFI/KVM kernel and module gates,
retain the qualified kernel36/34/23 boot entries, then boot the P16 and
exercise real CUDA/HMM video workloads with Lockdep enabled. Only that native
sequence can close the runtime finding or support post-resume media claims.
