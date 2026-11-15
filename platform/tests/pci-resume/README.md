# PCIe and SDHCI resume regressions

These are developer tests, never installed as driver startup helpers. Production
changes are ordinary Linux PCI/SDHCI C patches in `kernel/PKGBUILD`:

- `pciehp-defer-system-resume.patch` queues replacement events in noirq resume
  and dispatches them during regular system resume. Runtime resume is unchanged.
- `sdhci-irq-ownership.patch` releases only an owned IRQ action, including removal
  after suspend or failed resume. It also drops a retained IRQ wake vote before
  removing the action, without accessing a disconnected device's registers.
- `pciehp-reset-lock-order.patch` removes reset-lock nesting around scan/remove
  and serializes bus resets against those operations. Contention returns
  `EAGAIN`; it must not block a reset worker behind removal flushing that worker.
  VMD probe and the final GPU fixup use an explicit owning-enumeration variant.

The system-resume event correction follows an
[upstream proposal](https://lists.openwall.net/linux-kernel/2026/10/18/921).
The locking design follows the
[PCI serialization discussion](https://lists.openwall.net/linux-kernel/2026/08/18/401),
with nonblocking reset admission and DSN publication kept under the controller
lock. These are downstream changes, not a claim of mainline acceptance.

## Portable callback regressions

Use the prepared predecessor source, before these three patches:

```sh
python3 platform/tests/pci-resume/test_resume.py \
  --source /path/to/prepared/linux-7.2.8 \
  --output build/pci-resume-portable
```

The script copies only the affected files, applies the production patches with
zero fuzz, and extracts the actual C functions. Both old and fixed callbacks
run under ASan/UBSan. The old variants are positive controls: they must exhibit
the duplicate IRQ release, leaked wake vote, early IRQ-thread wake, and cyclic
lock-order graph that the fixed variants avoid. The manifest pins input,
patch and binary hashes.

The fixtures cover eleven SDHCI lifecycle/error paths, 24 replacement/PME/
polling signal-policy combinations, scan/remove unwind, slot/bus reset paths,
and real pthread mutex contention. The lock-order recorder is a reduced model,
not kernel Lockdep. The signal-policy fixture does not qualify the real polling
thread or firmware-managed PME. The workstation uses native PME; its host-power
gating policy separately rejects polling controllers.

## Real kernel hot-removal in KVM

Build the guest kernel and matching SDHCI modules first. Provide ARM64 AAVMF
firmware containing `AAVMF_CODE.no-secboot.fd` and `AAVMF_VARS.fd`:

```sh
python3 platform/tests/pci-resume/run_vm.py \
  --kernel /path/to/built/predecessor/kernel \
  --firmware /path/to/AAVMF --expect-legacy \
  --output build/pci-resume-vm-old

python3 platform/tests/pci-resume/run_vm.py \
  --kernel /path/to/built/patched/kernel \
  --firmware /path/to/AAVMF \
  --output build/pci-resume-vm-fixed
```

Only an emulated empty SDHCI controller (`1b36:0007`) is admitted by the fixture,
with both a QEMU DMI guard and `run_test=1`. The guest loads its own normal
SDHCI modules, suspends that empty host, and waits for QMP to remove its parent
bridge. Old code must produce exactly the known IRQ and Lockdep warnings;
fixed code must produce neither and must retain `debug_locks=1`. KASAN/BUG/Oops failures never count as a pass.
The static init program refuses to run outside PID 1.

Add `--guest-pm` to either command to exercise the actual kernel suspend/noirq/
early/regular resume callbacks. The guest selects `pm_test=platform`; QMP and
QTest emulate surprise unplug during its five-second suspended window. QTest
writes only the virtual root port's PCI configuration, restoring powered-on
slot semantics before the guest resumes. The test records a function/event
trace: old code must explicitly wake the IRQ thread inside noirq resume;
fixed code must not, and removal must follow early-resume completion. The same
IRQ, warning and Lockdep checks apply. This is guest-only device PM, not a
physical platform-sleep qualification.

The runner uses one vCPU, 4 GiB RAM, a private EFI image and a bounded timeout.
It never loads a host module, requests host sleep, changes the power profile,
or writes boot files. Its generated kernel retains its own artifact identity;
a passing VM result does not qualify native s2idle or physical SD-card use.
Use optional `--cpus N ...` to limit the runner's host affinity; no machine's
CPU numbering is assumed by default.
