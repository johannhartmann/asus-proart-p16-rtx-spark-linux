# Diagnosing the current audio test boot failure

The kernel31 shutdown/reload candidate is **not hardware-qualified or confirmed
bootable**. On 12 November 2026, selecting `RTX-Spark-Audio-Test` produced an
immediate black screen that remained for ten minutes. The failed attempt did
not leave a persistent kernel31 journal entry. Use the working kernel23 default
or recovery entry while investigating.

The failed ARM64 `Image` has SHA-256
`ab39c02c03334e5cd665758502cde89f04667572112e34494f7bba3bacc69fd1`.
The previously working kernel31 image has SHA-256
`786ba498bd872a33b51b2eccefadb28888f007183bb171866079e90551b1c7b8`.
Their ARM64/PE headers match. Comparing the saved UKIs also found identical EFI
stub sections, initramfs and ACPI payload; the kernel changed, along with a
trailing command-line space. The cause has not been established.

Both kernel images passed isolated direct and EFI/KVM startup with KASLR and a
minimal userspace test covering vDSO time reads, signal return and fork. EFI
framebuffer early-console setup also worked in the virtual platform. These
checks do not exercise N1X ACPI, SSPM, NVIDIA graphics or DSP hardware. A later
abrupt restart of the kernel23 host remains unexplained; further VM testing on
that host was initially stopped. On the user's request, a later serialized batch
ran 18 more KVM boots: six direct and three EFI/framebuffer boots for each image,
with one vCPU and 2 GiB RAM per guest. All 18 passed while other workloads stayed
running. No host freeze was reproduced during the batch or more than five
minutes after the final guest exited. A separate Qwen workload then coincided
with ACPI thermal readings reaching 95.2 C while no VM was running; this does
not establish the cause of the earlier freeze. Do not treat the virtual smoke
tests as physical qualification of the N1X startup path.

A logging-only replacement was first installed as
`RTX-Spark-Audio-Diagnostics`, retaining the failed kernel and initramfs while
preserving the working kernel23 default and recovery entries.

## Scoped SSPM correction

The old/new object comparison narrowed executable-code changes to SSPM and
PowerWrap. In particular, the failed candidate replaced the normal transport's
bounded late-ACK drain with a permanent rejection of every later SET after one
submitted timeout. Since platform boot and power management share that
transport, this could disable subsequent device power transitions. No log from
the failed native boot establishes that such a timeout actually occurred; the
previous successful kernel31 journal contains no recorded SSPM timeout.

The corrected patch restores the original normal transport and adds
`sspm_ci_set_checked()` only for the destructive DSP-shutdown helper. Every
submitted timeout still permanently disqualifies checked shutdown commands.
Rebinding, a late ACK or successful normal recovery cannot clear that history
or authorize DMA reclamation. All six existing PowerWrap dispatch callers,
plus the direct probe and request paths, retain normal transport semantics.

The actual old/new normal sender functions produced identical results across
73 simulated transactions, including timeout, late-ACK drain and rebind.
Separate sanitizer tests cover checked refusal, normal recovery after a
checked timeout, native D3/abandon wire payloads and partial-stage handling.
These tests establish the intended software boundary, not physical bootability.
The corrected kernel is rebuilt from the previously working kernel31 tree,
with the same configuration and build identity, applying only the scoped
SSPM/PowerWrap patch. Hardware startup and full audio reload remain pending.

The scoped candidate is now installed in `RTX-Spark-Audio-Diagnostics`, with
matching kernel31 `vmlinuz`, System.map, debug-stripped vmlinux and symbol
versions. Its kernel SHA-256 is
`5b3282f08458c3bfc59e89218f6fe78f0ac3e830a81ea3ed859820db5de9fb2a`;
the UKI SHA-256 is
`e45bea823803eabd2f687a7597c8fe3cfb2f58b69c67fcd316e65dff6357ea06`.
Only the kernel payload changed from the logging-only UKI: initramfs, ACPI,
EFI stub, command line and section load addresses are preserved. The Limine
BLAKE2b pin was updated and verified. Kernel23 remains the default; recovery,
other entries, installed modules, live drivers and power profile are unchanged.
The previous test bundle is backed up under
`/var/lib/p16-platform/audio31-scoped-shutdown-20261112`.

All 162 repository tests and the offline driver suite passed. All 8,509
installed modules' 442,068 symbol imports match the new kernel and installed
module exports; existing kernel export CRCs are unchanged. Direct KVM startup
passed. The additional EFI run was stopped by the host-temperature guard at
90 C before reaching the userspace marker; it is not a passing EFI result or a
confirmed kernel failure. The host remained on the same boot. No claim of
successful native boot or completed DSP reload follows from these checks.

## Prepare early-console evidence

The staging tool changes only the command line of an unsigned copy of the
failed test UKI. It retains the kernel, initramfs, load addresses, encryption
arguments and DSP/ACPI policy. It refuses output under `/boot` or `/efi` and
never installs an image or changes a boot selection:

```sh
python3 scripts/stage-audio-boot-diagnostics.py \
  --source /path/to/saved-failed-kernel31.efi \
  --output /path/to/new-private-diagnostics-directory
```

The output contains the candidate UKI, command line and a manifest pinning the
unchanged sections. It enables `efi=debug`, `earlycon=efifb`, informational
console output and a larger kernel log buffer. Initcall tracing is retained in
the log buffer. Initramfs messages go to the kernel log and
`/run/initramfs/init.log`; that file is not persistent across a reset. Automatic
panic reboot is disabled so visible failures remain available for inspection.
The EFI early console depends on usable firmware framebuffer metadata and
hands off when a normal console registers. It cannot guarantee a saved log if
the machine locks before logging or root-filesystem startup.

Install only through a reviewed, backed-up boot transaction that verifies the
manifest and updates the Limine BLAKE2b hash. Preserve the working kernel23 and
recovery images, command lines and default selection. Capture the first visible
failure before attempting another modification. This command-line-only staging
tool gathers evidence; it does not apply the scoped kernel correction described
above.
