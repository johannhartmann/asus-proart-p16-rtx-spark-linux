# MMU interval notifier Lockdep regression

This guest test models NVIDIA UVM's HMM notifier sequence: register the MMU
notifier under the process's mmap write lock, then insert an interval notifier
while holding its mmap read lock. The original kernel's unconditional
`might_lock(&mm->mmap_lock)` reports recursive locking in that second step,
although the pre-existing subscription means insertion does not acquire the
write lock. The candidate moves `might_lock()` into the registration branch.

The model also tests the ordinary path without pre-registration or a held
mmap lock. All runs use a fresh AArch64 EFI/KVM guest with `PROVE_LOCKING=y`;
the runner checks warning count, `debug_locks`, host boot ID and power profile.
It does not load a host module, change host PM or emulate the N1X GPU.

Build the model against the exact kernel tree whose Image is under test:

```sh
mkdir -p /tmp/n1x-mmu-test
cp Kbuild n1x_mmu_notifier_lock_test.c /tmp/n1x-mmu-test/
make -C /path/to/kernel-tree M=/tmp/n1x-mmu-test modules
```

Run the failing control on the original Image and the two passing cases on
the patched Image, using a firmware directory with
`AAVMF_CODE.no-secboot.fd` and `AAVMF_VARS.fd`:

```sh
python3 run_vm.py --kernel /path/to/original-kernel-tree \
  --firmware /path/to/AAVMF --module /tmp/n1x-mmu-test/n1x_mmu_notifier_lock_test.ko \
  --output /tmp/mmu-original --pre-register --expect-warning
python3 run_vm.py --kernel /path/to/patched-kernel-tree \
  --firmware /path/to/AAVMF --module /tmp/n1x-mmu-test/n1x_mmu_notifier_lock_test.ko \
  --output /tmp/mmu-fixed --pre-register
python3 run_vm.py --kernel /path/to/patched-kernel-tree \
  --firmware /path/to/AAVMF --module /tmp/n1x-mmu-test/n1x_mmu_notifier_lock_test.ko \
  --output /tmp/mmu-fallback
```

The [18 November evidence](../../../docs/evidence/mmu-notifier-lockdep-20261118.md)
records the exact P16 source, patch, Image and module hashes and the three
observed results. A physical P16 boot and real CUDA workload are separate
qualification gates.
