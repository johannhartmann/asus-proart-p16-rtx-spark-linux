# Bus notifier lock-class model

This disposable-QEMU test reproduces a reduced cross-bus lock-class cycle.
It does not initialize N1X hardware, alter the host kernel or provide a driver
startup path. The module requires both `run_test=1` and a QEMU DMI vendor.
The included static init program refuses to run outside PID 1.

`bus_register()` in the tested kernel initializes every blocking bus notifier
head at one `BLOCKING_INIT_NOTIFIER_HEAD()` call site. The native kernel34
warning joins an NVIDIA I2C adapter registration to a platform-bus IOMMU
notification through that shared class, then closes through CPU hotplug,
perf and `mmap_lock`. The IOMMU bus list does not include the I2C bus.
This model tests that class-merging mechanism; it does not prove that every
native dependency is harmless or resolve the native warning.

The model learns `A -> notifier-A`, `notifier-B -> B`, then `B -> A`.
Run each case in a fresh guest with Lockdep initially enabled:

| Parameters after `run_test=1` | Expected result |
| --- | --- |
| `unique=0 same_bus=0` | Shared classes produce a circular-locking warning despite independent heads; `debug_locks=0`. |
| `unique=1 same_bus=0` | Distinct classes avoid that cross-head warning; `debug_locks=1`. |
| `unique=1 same_bus=1` | The same-head positive control still produces the warning; `debug_locks=0`. |

Build the module against the guest's exact kernel with normal Kbuild:

```sh
make -C /path/to/guest/kernel/build M="$PWD" W=1 modules
cc -static -O2 -Wall -Wextra -Werror \
  '-DMODEL_PARAMETERS="run_test=1 unique=1 same_bus=0"' init.c -o init
```

Place `init` at `/init` and the module at `/model.ko` in a guest initramfs,
with `/dev` and its console node. Boot that image in an isolated QEMU guest.
The init program loads the model and powers off the guest after success.
Never install the model into the workstation's module set or boot images.

All three cases passed in separate EFI/KVM guests with kernel34, one vCPU
and 4 GiB RAM. Per-head keys here belong only to the test objects. No driver-core
annotation change or Lockdep reset was applied to the running workstation.

Related upstream discussion: [bus notifier and CPU hotplug dependencies](https://lkml.rescloud.iu.edu/2209.2/05998.html),
[perf user-copy and mmap locking](https://lkml.iu.edu/2011.2/06036.html).
