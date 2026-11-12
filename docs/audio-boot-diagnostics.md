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
that host was stopped. Do not treat these smoke tests as physical qualification.

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
failure before attempting another modification. A diagnostic image is evidence
gathering, not a correction of the underlying boot failure.
