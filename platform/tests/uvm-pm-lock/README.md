# UVM PM lock-order regression

Development-only, disposable EFI/KVM tests. They never install/load a host
module, request host sleep, or access a real GPU. The module requires QEMU DMI,
`run_test=1` and an initially enabled Linux Lockdep validator. Guest init requires
PID 1 and QEMU. The runner uses one vCPU, 4 GiB RAM, a 120-second timeout and a
90 °C host thermal cutoff; it preserves the host boot and power profile.

`prepare.py` copies NVIDIA **615.78.08** UVM source, applies the maintained patch
with zero fuzz for the fixed variant, then extracts the actual `uvm_suspend()`,
`uvm_resume()` and VA locking macros. Only hardware/queue operations and vendor
tracking are stubbed; mutexes, rwsems, Lockdep and the competing kernel thread
are real Linux facilities. Source, patch, extracted code and module hashes are
recorded in the output manifest. Use pristine vendor source and the exact
LOCKDEP-enabled guest kernel build tree.

```sh
python3 platform/tests/uvm-pm-lock/prepare.py \
  --source /path/to/NVIDIA-615.78.08 --kernel /path/to/kernel/build \
  --output /new/build/fixed
# Repeat with --legacy and a different output directory for the control.
python3 platform/tests/uvm-pm-lock/run_vm.py \
  --kernel /path/to/kernel/build --firmware /path/to/AAVMF \
  --module /new/build/fixed/n1x_uvm_pm_test.ko \
  --output /new/result/fixed2 --va-spaces 2
```

The firmware directory must contain `AAVMF_CODE.no-secboot.fd` and
`AAVMF_VARS.fd`. The runner requires native AArch64 KVM, a static C compiler,
QEMU, mkinitcpio, systemd's ARM64 EFI stub and the kernel's `gen_init_cpio`.
It assembles its own private guest UKI; no host boot files change.
Use `--cpus` for optional host affinity without hardware-specific defaults.

Run each row in a fresh guest:

| Variant / runner options | Expected |
| --- | --- |
| Legacy module, `--legacy --va-spaces 0` | One cycle, Lockdep active. |
| Legacy module, `--legacy --va-spaces 1`, `2`, `8` | One cycle, original inversion or recursive-class warning, Lockdep disabled by that warning. |
| Fixed module, `--va-spaces 0`, `1`, `2`, `8` | Four cycles, no warning, Lockdep active. |
| Fixed module, `--va-spaces 1 --positive` | Four clean cycles, then an intentional inverse acquisition produces a warning. |

Module and runner must agree on the variant. The runner checks the complete
result fields, warning count/type and absence of unrelated kernel failures.
Each cycle checks retained VA locks, PM state, GPU callbacks, released locks and
completion of a PM-reader/list mutator only after the writer is released.
A reader may acquire PM immediately after resume releases it, including during
the deferred-release queue flush; the current task must no longer hold PM then.

All nine cases passed against kernel36. This proves the reproduced lock path
and positive control, not GPU hardware, list mutation call-site completeness
or physical sleep. The production patch depends on the audited creation and
release paths retaining their PM read grants and on the existing same-task PM
owner fix. Re-audit those paths for every new vendor version. Test modules and
Python tooling are never part of the installed driver or startup path.
