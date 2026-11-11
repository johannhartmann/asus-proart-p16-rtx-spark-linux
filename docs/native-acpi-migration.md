# Retire the reference SSDT override

Status: test tooling is available; physical comparison is pending. The default
package profile remains legacy. A separate native test entry can be installed
without selecting it or changing the working/recovery images. The candidate
must pass physical qualification before the legacy dependency is removed.

## What the test changes

The reference SSDT replaces response buffers in EC methods `RRA9`, `RRA8`,
`WRA9`, `WRA8`, `RWEC` and battery method `GBST`. We need to determine whether
that workaround is still necessary with the current FF-A/FFH kernel handling.
The older captured DSDT was already removed; its SSPM-discovery workaround is
handled by the existing negative Windows-2022 OSI policy.
The reference builder now requires only the original ASUS SSDT and generates
only its verified replacement, with no DSDT transformation or combined CPIO.

This test removes only `kernel/firmware/acpi/SSDT.aml` from the early initramfs
of a known working UKI. The kernel, command line, embedded modules, other PE
section payloads, retained early-CPIO records and compressed main initramfs
payload remain byte-identical. This isolates the SSDT change from kernel,
module, firmware and DSP development.

## Prepare an image without installing it

From this repository, as a normal user when the source image is readable:

```sh
python3 scripts/stage-native-acpi.py \
  --source /path/to/known-working.efi \
  --output build/native-acpi-candidate
```

On the development machine `/boot` is protected. To read the hash-pinned Limine
default and write only a new staging directory, use graphical authentication:

```sh
pkexec --disable-internal-agent /usr/bin/python3 \
  "$PWD/scripts/stage-native-acpi.py" --source-default \
  --output "$PWD/build/native-acpi-candidate"
```

The tool produces `native-acpi.efi` and `manifest.json`; it has no installation,
menu-selection or reboot option. It rejects an existing output directory,
outputs under `/boot` or `/efi`, unexpected ACPI overrides, signed/PCR-signed
inputs and failed payload checks. It never strips a signature to obtain a
passing result. An enforcing signing/measured-boot setup needs its normal
rebuild and signing procedure instead.

Both source and candidate pass the repository's boot-image verifier. Legacy
mode requires the exact reference SSDT. Native mode rejects all ACPI override
files, including tables in the compressed main archive; it does not require
the override allocator or `CONFIG_ACPI_TABLE_UPGRADE`. Kernel ownership,
module dependencies, required platform configuration and command-line checks
still apply. The manifest records source/candidate hashes, source and running
kernel releases, unchanged section hashes and the preserved main-initramfs tail.
It explicitly records `hardware_qualified: false`.

Recheck a staged image without changing boot files:

```sh
python3 scripts/verify-boot.py --image build/native-acpi-candidate/native-acpi.efi \
  --image-only --acpi-mode native
```

Policy package 1.3.0 also provides explicit native-image checks through
`p16-platform-update-check --image IMAGE --acpi-mode native`. Its automatic
update hooks still select legacy mode. The new checker/helper are prepared
source changes, not a reason to upgrade policy or rebuild working UKIs before
the controlled test.

## Controlled boot and comparison

The source UKI must have passed a normal boot. If the manifest's source release
differs from the currently running release, first collect the baseline on that
source kernel. Keep package/module versions and the command line unchanged
between baseline and candidate. Use a baseline without experimental DSP
publication so the ACPI test does not also become a DSP recovery experiment.

Install the staged candidate through the separate helper:

```sh
pkexec --disable-internal-agent /usr/bin/python3 \
  "$PWD/scripts/install-native-acpi-test.py" \
  --candidate "$PWD/build/native-acpi-candidate"
```

It revalidates the source against the hash-pinned default and the staging
manifest, verifies that only the reference SSDT was removed, and rejects DSP
autostart parameters. It backs up `limine.conf`, adds only the test image/entry
shown below, then verifies all menu hashes and the unchanged default/recovery.
The operation uses the existing boot-partition lock and refuses to replace an
existing test image, entry or installation record. `installation.json` records
the backup and installed image hashes separately from the staging manifest.
The helper never selects an entry, changes packages or reboots.

The helper preserves the existing working and recovery entries and installs
`/boot/EFI/Linux/p16-native-acpi-test.efi` with a separate top-level entry:

```text
/Omarchy-P16-Native-ACPI-Test
    protocol: efi
    path: boot():/EFI/Linux/p16-native-acpi-test.efi#BLAKE2B_DIGEST
```

Do not change the default entry. Select the test manually in Limine. Retain
the source kernel's root-filesystem modules and headers; the staged image is
not an independently updated kernel package. Rebuild/reverify the candidate
after any relevant package change rather than relying on an old artifact.

Record the manifest hash, actual kernel, BIOS, boot ID and relevant kernel logs
for each boot. Confirm the active ASUS SSDT is the original firmware table,
not the reference override hash
`9b28ffc14c19f8b7ea2278de88ff9ec070f5f70401107d81fef067a916aa9695`.
Check `/sys/firmware/acpi/tables/SSDT*` and the ACPI table-upgrade boot messages;
matching `uname -r` alone cannot distinguish these two images.

On the source boot, capture the legacy baseline; repeat on the native boot
with `--phase native` and a new output directory:

```sh
pkexec --disable-internal-agent /usr/bin/python3 \
  "$PWD/scripts/collect-native-acpi.py" \
  --candidate "$PWD/build/native-acpi-candidate" --phase legacy \
  --output "$PWD/build/native-acpi-candidate/legacy-before"
```

The collector records table hashes, boot/kernel/command-line identities, DSP
publication state, battery/profile/hwmon readings, module identities and the
kernel journal. It rejects admission if the kernel, command line or expected
ASUS SSDT differs, or a DSP is published. It preserves unavailable readings as
errors. Its reports are observations and always have `hardware_qualified: false`;
the physical checks below must be performed and recorded separately. Capture
new snapshots after AC changes and resume. Do not treat identical failures on
both boots as passing qualification.

| Area | Required comparison with the legacy baseline |
| --- | --- |
| EC / FF-A / FFH | No new ACPI exceptions, failed EC transactions, mailbox timeouts or method errors involving the changed methods. No raw EC/register probes. |
| Battery status | Valid, changing charge/energy, voltage and current/power readings; AC connection/disconnection produces the expected status transition. Merely enumerating `BAT0` is insufficient. |
| Charge threshold | A supported threshold can be read, deliberately changed and read back; restore the original setting. Record unavailable controls and failures on either image rather than treating them as success. |
| Firmware profiles | Advertised profiles remain available; controlled selection/readback works and the original profile is restored. |
| Monitoring | ASUS fan/thermal and N1X telemetry interfaces remain available without new EC errors. |
| Stability | Repeat normal baseline activity, then a separately controlled suspend/resume comparison with no published DSP firmware. Record recovery and post-wake EC/battery/profile behavior. |

Different battery readings between boots are normal; compare functioning and
plausibility, not identical numeric values. A pre-existing baseline failure
does not qualify the corresponding candidate function. Source tests, image
verification and equal metadata do not establish physical EC behavior.

On any regression, return to the preserved legacy entry. Keep the failed
candidate and logs for diagnosis; do not remove the reference firmware package,
reset the EC or patch live AML as a workaround for the test.

## Default-package removal after qualification

Only after the comparison passes:

1. Change initramfs generation to native mode by default and make the legacy
   `p16-acpi` hook explicitly opt-in.
2. Remove the mandatory `p16-acpi-firmware` dependency from platform policy and
   the default package build set; retain the exact-input builder as historical
   recovery material.
3. Switch managed update checks to the selected native profile, while keeping
   strict verification of explicitly preserved legacy recovery images.
4. Update installation/audit documentation and requalify a normal package
   transaction, generated UKI and fresh boot before promoting the default.

The current preparation deliberately does not execute those migration steps.
