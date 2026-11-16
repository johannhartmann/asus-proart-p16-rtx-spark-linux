# Suspend and deferred audio START corrections

These changes address independent source/configuration defects. They
must be qualified together; passing a build or a VM test does not establish
physical suspend/resume on the workstation.

The running validation kernel is **`7.2.8-36-rtx-spark-npu`**, selected through
**`RTX-Spark-Kernel36`**. Its [initial staging record](evidence/resume-kernel36-staged-20261116.json)
pins the original EFI and kernel hashes. The complete bundle includes AFE
0.1.29 and the PCIe/SDHCI corrections below. Its native cold boot, two checked
audio reloads, 18 PCM cases, four desktop playbacks and 24 numerical cuDLA
outputs passed with Lockdep active through those phases.

The following device-only PM transaction returned, with all three DSPs freshly
ready and their configuration restored, but **failed qualification** on a new
NVIDIA UVM lock inversion. Lockdep disabled itself on that warning; it was not
reset. Physical sleep was not attempted. The
[native record](evidence/kernel36-native-20261116.json) separates these results
from the earlier collector-only failures, which exercised no PCM or PM.

The [UVM correction](../platform/nvidia/README.md#uvm-pm-collection-and-resume-lock-order)
avoids reacquiring the global VA-list mutex under retained VA locks and uses
proper nested locking for the VA collection. Its nine fresh kernel-VM tests
passed, including original and deliberate-inversion controls. The corrected
UVM module targets the unchanged kernel36 Image and BTF; no new Linux kernel
build is needed. See the [regression record](evidence/uvm-pm-lock-20261116.json).
The new UVM module still needs native cold-boot and physical-sleep qualification.

Kernel34 remains the normal default. Kernel35 and recovery23 remain available;
the existing `legacy` ACPI profile, boot arguments and selected `quiet` power
profile are preserved. The initial kernel36 staging verified all 8,503 installed
production modules and all 430 embedded modules against the exact BTF and
installed bytes. No candidate is promoted on an offline test alone.

Kernel35 previously passed its helper-free cold boot and device-only PM but
reproduced an intermittent first-START `EBUSY` after reload; physical sleep
returned with PCIe/SDHCI warnings. Those results remain historical evidence in
the [kernel35 record](evidence/suspend-kernel35.json). Kernel36's passing audio
runs do not retrospectively identify the cause of that START failure.

## Audio: a deferred DPCM START is allowed to see a running FE

Linux ASoC's `dpcm_fe_dai_trigger()` queues a trigger while a routing update
is active, returning success to ALSA. ALSA can then change the FE state to
RUNNING before `dpcm_set_fe_update_state()` delivers the queued START. The
MT8901 machine driver uses dynamic DPCM frontends, so this path applies here.

AFE 0.1.27's `mt8901_afe_sram_endpoint()` rejected that running state. The DSP
START path calls this getter to validate the prepared endpoint, so a legal
deferred START could return `EBUSY`. AFE **0.1.28** makes the metadata snapshot
readable while running. Ownership, geometry, retirement and size checks remain;
publication, binding and preparation still reject a running stream. The change
does not retry firmware commands, rewrite an active IRQ or release DMA memory.

`platform/dsp/afe/test_sram.py` runs the actual owner code with the unmodified
ASoC deferred-trigger functions in `dpcm-trigger-fixture.h`. With identical
inputs, the old gate returns `-16` and the fixed getter returns `0`. Both reject
live publication/preparation, and the fixed getter still rejects changed
geometry or ownership and retired streams. The full SRAM/PM/fault matrix runs
under AddressSanitizer/UBSan for both variants.

This identifies and fixes a concrete intermittent START defect. The original
single native failure did not record its ALSA runtime state, so it cannot be
retrospectively attributed to this path with certainty. A total of 48 traced
playbacks and twelve first-start requests across four checked module reloads
did not reproduce that earlier failure. Those functional diagnostics ran with
that diagnostic boot's already disabled Lockdep; they are not locking qualification.

The fixed AFE 0.1.28 module was then loaded on the running kernel34 without a
reboot. Six playback/capture/duplex cases and eight independently verified
cuDLA outputs passed. That confirms bounded functional operation with the fix;
that diagnostic boot's already disabled Lockdep is still not locking qualification.

The kernel35 run reproduced START `EBUSY` after its first checked audio reload.
A subsequent function-graph diagnostic passed two playbacks around one reload.
Four further checked reload cycles passed 24 PCM cases and 32 independently
verified cuDLA outputs with continuously enabled Lockdep and no new kernel
warning. Those probes were attached before unloading the modules, so they
do not establish error-path coverage after reload. The corrected collector
reattaches to each loaded module generation before audio services restart and
requires nonzero probe counters. The tests waited for transient desktop audio clients to release their channels;
they did not retry a failed PCM START. These passing runs do not explain or
close the initial intermittent failure.

A later collector attached probes after each module load, before restarting
desktop audio, and verified nonzero FE/DSP/endpoint/IRQ counters. Four reloads
produced seven successful playbacks; the eighth request failed at PCM OPEN
with `EOPNOTSUPP`, without a traced START refusal. The sequence stopped there.
AFE **0.1.29** separately corrects a source defect in this path: DL0 and DL1
share one firmware playback owner, and an already occupied direction must
return `EBUSY`, not `EOPNOTSUPP`. The actual-C frontend regression verifies
that both competing frontends preserve the current owner and its allocation
and symbol leases. This errno correction does not establish the cause of the
earlier START failure; live contention and replacement qualification are
recorded separately.

On 16 November, [native AFE 0.1.29 qualification](evidence/afe29-live-20261116.json)
reproduced the occupied-direction refusal with AFE 0.1.28 (`-95`) and the
correct `EBUSY` response with 0.1.29 (`-16`). The module was replaced on the
running kernel35 without rebooting. Two checked reloads passed twelve PCM
cases, including nonzero capture and duplex in both formats. Eight further
reloads passed sixteen immediate first-start playbacks with desktop audio
running. Probes were attached to each new module generation before desktop
audio restarted, with nonzero FE/DSP/endpoint/IRQ counters. All eight numerical
cuDLA outputs and buffer reuse passed afterward. There was no new kernel
warning or power-profile change. The earlier START `EBUSY` was not reproduced;
its cause remains unproven. Lockdep was already disabled by the recorded
PCIe/SDHCI warning, so this is bounded functional qualification, not clean
locking or physical-sleep qualification.

## Lockdep: separate unrelated bus notifier classes

The native NVIDIA/IOMMU/perf warning joins I2C and platform bus callbacks via
one class key created by `bus_register()`'s shared notifier initialization
site. `kernel/bus-notifier-lock-class.patch` gives each bus notifier rwsem its
own registered key, following the existing subsystem mutex lifetime. Both
registration failure and final bus release retire the key. No validator or
lock is disabled, and dependencies within one bus remain checked.

The [real driver-core regression](../platform/tests/bus-notifier-lock/README.md)
registers actual Linux buses, devices and notifiers. The old kernel warns for
independent buses, the patched kernel stays at `debug_locks=1`, and the patched
same-bus positive control still warns. Each case runs in a fresh EFI/KVM guest.
This is stronger than the earlier reduced model, but native continuously
enabled Lockdep still requires booting a matching complete kernel/module set.
Never reset the running boot's disabled validator to claim a pass.

## Suspend: switch VT before freezing user sessions

The [optional systemd package](../platform/nvidia/sleep/README.md) makes the
console handoff a required predecessor of `systemd-suspend.service`, then
enables systemd's early user-session freeze. It restores the previous VT on
resume and abort. This addresses the reproduced exec/freezer race without
making `de_thread()` freezable while it holds exec locks. It uses normal
systemd dependencies and a small shell helper, with no firmware or module
startup logic.

The existing NVIDIA PM-owner correction remains required: the same dedicated
kernel thread owns the NVIDIA PM gates from PREPARE through POST. VT ordering,
gate ownership and bus Lockdep classes solve different problems; none replaces
the others.

Install `config/90-rtx-spark-suspend.conf` under `/etc/systemd/sleep.conf.d/`
for the N1X workstation. It selects only `mem` with `s2idle`, matching the
device-only qualification sequence. Other systemd fallback sleep states must
not retry a device/firmware transition after an uncertain failure. This is a
Linux sleep-policy setting, not a driver admission gate or a power-profile
change.

## Physical resume: PCIe hotplug and SDHCI remain blockers

The normal VT service completed before `systemd-suspend.service` began and
before systemd froze `user.slice`. The device-only test used this installed
ordering, with no manual VT switch or temporary service override. The prior
VT and unfrozen session were restored automatically.

The subsequent physical cycle spent 98.764 seconds in s2idle. All three DSPs
returned ready with `cycles=2`, error zero and matching restored configuration;
NPU firmware REINIT also reported error zero. Qualification stopped before
new PCM or numerical NPU workloads because the kernel warned during resume.
These firmware readbacks are not post-resume functional qualification.

PCIe hotplug removed the GL9767 SD reader (`17a0:9767`, revision `04`) during
the noirq resume phase. `sdhci_suspend_host()` had already freed its IRQ;
`sdhci_remove_host()` freed it again, producing the already-free IRQ warning.
`pciehp_unconfigure_device()` then triggered a circular dependency between
`reset_lock` and `pci_rescan_remove_lock`, disabling Lockdep. The desktop
returned, but the physical test is **failed**, not a clean suspend/resume pass.
No validator reset, further suspend request or reboot was used to hide it.

The installed source calls `pciehp_request()` from `pciehp_resume_noirq()`;
that function wakes the IRQ thread directly. A matching
[upstream proposal](https://lists.openwall.net/linux-kernel/2026/10/18/921)
defers replacement handling to regular resume. The
[follow-up discussion](https://lore-kernel.gnuweeb.org/linux-usb/20261108051829.152803-1-cole%40unwrap.rs/T/)
confirms that the proposal is not an established mainline fix. A separate
[locking RFC](https://lists.openwall.net/linux-kernel/2026/08/18/401) changes
hotplug and PCI reset serialization together. The subsequent [source corrections and regressions](../platform/tests/pci-resume/README.md)
implement deferred replacement, explicit SDHCI IRQ ownership and PCI reset/scan
serialization in the package recipe. Their portable tests and real-kernel old/fixed KVM hot-removal cases pass.
A second KVM case unplugs the virtual reader while the guest is suspended at
`pm_test=platform`. Function/event traces show the old IRQ-thread wake and
removal inside noirq resume; fixed code removes it only after early resume.
Both cases enforce the same warning and continuously enabled Lockdep checks
for the fixed kernel. The PCI/reset/hotplug/VMD changes also pass an x86-64
LLVM `W=1` compile check.
The fixed guest keeps Lockdep enabled without either warning; the old positive
control must reproduce both warnings and disable Lockdep. The
[evidence record](evidence/pci-resume-fixes-20261115.json) pins those separate
Images and patch hashes. Native qualification remains a separate gate. They have not replaced the running kernel.
The earlier audio START `EBUSY` remains a separate open issue.

The complete **kernel36** kernel/header/driver bundle is now built separately;
its [offline artifact record](evidence/resume-kernel36-offline.json) pins all
three packages and the exact Image. All 8,507 built modules pass split-BTF
checks. Twelve EFI/KVM cases cover 30 module loads and native protocol KUnit,
the AFE IRQ lifetime, Lockdep capacity, PCIe hot-removal and noirq resume, real
bus notifiers, NVIDIA PM-owner error unwinds and the exec/freezer regression.
The same-bus notifier positive control intentionally requires a warning; clean
cases require the validator to remain enabled. The 177 repository tests pass.
That initial offline bundle was not installed or selected for boot. Live first-START diagnostics
on the existing kernel had to finish before requesting the next native boot;
these offline results do not close the intermittent audio failure or qualify
physical sleep on kernel36.

The [AFE 0.1.29 bundle](evidence/resume-kernel36-afe29-offline.json) supersedes
that initial offline kernel36 build. Its final Image passed four fresh EFI/KVM
cases: the complete 30-module/protocol/AFE-lifetime test, Lockdep capacity,
SDHCI hot-removal and traced noirq resume. All 8,507 built modules and 8,503
packaged production modules pass split-BTF checks. The 12 earlier core cases
remain recorded against their own Image, with identical core patch inputs,
configuration and symbol CRCs. The AFE 0.1.29 bundle has since been installed
as an additional [validated boot entry](evidence/resume-kernel36-staged-20261116.json);
the initial bundle was not deployed. The [later live diagnostic](evidence/audio-open-20261115.json)
records seven successful playbacks followed by an OPEN refusal. AFE 0.1.29's
subsequent live contention/replacement results are recorded above. Kernel36
has since passed native cold boot and the pre-PM audio/NPU phases; the UVM
warning described above blocks overall PM qualification.

## Deployment gate

Keep the working kernel34 and recovery images. Build all changes into one
separately named candidate, rebuild every external module against its exact
vmlinux, and verify split BTF, the EFI image and menu hashes. Run the EFI/KVM
boot/module, real bus notifier, PM-owner failure-unwind and freezer regressions
before installing a complete candidate. Do not change the power profile.

The final hardware transaction must cover normal ACPI module startup, PCM and
cuDLA correctness, checked audio reload, normal suspend/resume and post-resume
audio/NPU operation, with Lockdep enabled throughout. Physical sleep remains
unverified until that transaction succeeds. A reboot solely for an incremental
audio test or to clear a warning is not a deployment gate.

The post-qualification global DKMS configuration is already prepared as
`n1x-nvidia-drm-fix 615.78.08-4`, carrying DRM, PM-owner and UVM patches. Its package
contents, source checksums and clean application to the pinned vendor source
were checked. The installed revision 2 remains unchanged until physical
qualification succeeds. Activating revision 4 needs no additional kernel build
or reboot and does not replace the running NVIDIA module.
