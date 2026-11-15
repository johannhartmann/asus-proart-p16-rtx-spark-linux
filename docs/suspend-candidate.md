# Suspend and deferred audio START corrections

These changes address three independent source/configuration defects. They
must be qualified together; passing a build or a VM test does not establish
physical suspend/resume on the workstation.

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
the current boot's already disabled Lockdep; they are not locking qualification.

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
