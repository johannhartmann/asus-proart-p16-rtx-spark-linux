# Suspend and deferred audio START corrections

These changes address three independent source/configuration defects. They
must be qualified together; passing a build or a VM test does not establish
physical suspend/resume on the workstation.

The installed candidate is **`7.2.8-35-rtx-spark-npu`**, available as
**`RTX-Spark-Kernel35`** in Limine. Its [qualification record](evidence/suspend-kernel35.json)
pins the kernel, UKI, package and BTF hashes and the test boundaries. The normal
kernel34 and recovery entries remain available. The native ACPI profile and
boot arguments were preserved. At staging, the obsolete kernel32 diagnostic
image was archived outside `/boot`. The subsequent
[boot cleanup](evidence/boot-cleanup-20261115.json) removed five more obsolete
or duplicate images and their obsolete kernel packages, retaining exactly
kernel34, kernel35 and recovery23. On 15 November, kernel35 booted through the
helper-free path with matching BTF and passed six PCM cases and eight numerical
cuDLA outputs with Lockdep enabled. After the first checked audio reload, the
first S16_LE playback START returned `EBUSY` (-16). This blocks overall
qualification: the AFE 0.1.28 correction does not cover every observed START
failure. A later device-only PM cycle under the installed normal sleep policy
passed with fresh DSP readiness, six PCM cases, eight cuDLA outputs and Lockdep
enabled. One physical s2idle cycle returned after about 99 seconds, but PCIe
hotplug/SDHCI warnings failed overall qualification. Kernel35 is not promoted
to the normal default, and global NVIDIA DKMS revision 3 is not activated.

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

The fixed AFE 0.1.28 module was then loaded on the running kernel34 without a
reboot. Six playback/capture/duplex cases and eight independently verified
cuDLA outputs passed. That confirms bounded functional operation with the fix;
the current boot's already disabled Lockdep is still not locking qualification.

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
The fixed guest keeps Lockdep enabled without either warning; the old positive
control must reproduce both warnings and disable Lockdep. The
[evidence record](evidence/pci-resume-fixes-20261115.json) pins those separate
Images and patch hashes. Native qualification remains a separate gate. They have not replaced the running kernel.
The earlier audio START `EBUSY` remains a separate open issue.

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
`n1x-nvidia-drm-fix 615.78.08-3`, carrying both DRM and PM patches. Its package
contents, source checksums and clean application to the pinned vendor source
were checked. The installed revision 2 remains unchanged until physical
qualification succeeds. Activating revision 3 needs no additional kernel build
or reboot and does not replace the running NVIDIA module.
