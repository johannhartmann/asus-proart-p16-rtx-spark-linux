# Isolated NVIDIA 620 root: staging and qualification boundary

This is the staging procedure for the ASUS ProArt P16 H7607BA, written from
the live kernel38/615 system on 18 November 2026 and updated with the
19 November staging results. NVIDIA 620 is installed in the isolated
`@nvidia620` snapshot and has **not** been booted. No reboot belongs to the
preparation phase. The machine currently uses a LUKS-backed Btrfs root subvolume `@`
(ID 256), with separate `@home`, `@log` and `@pkg` subvolumes. `/boot` is a
separate 2 GiB FAT EFI partition with about 801 MiB free. Limine remains the
kernel36 default; direct UEFI `Boot0003` currently selects kernel38 only when
explicitly chosen.

## Immutable inputs and rollback

The signed Arch Linux ARM `nvidia-utils` and `nvidia-open-dkms` 620.70.06-1
archives were verified against the trusted Build System key. Their SHA256
values are recorded in [the 620 offline audit](n1x-media-20261118/nvenc-620-offline.md).
The alternate kernel38/620 driver package SHA256 is
`2f669e17dc68f4f3227c1e9e2a4c54405c8e54c72eeb2bc4d89982cdb77a6232`;
the pinned DRM/PM/UVM DKMS patch package SHA256 is
`23b3ef76307ab1668a2a6666f081a7e5a52e9f1af25708ffd2d89ab90e10e023`.
All five 620 modules have already built against the final kernel38 ABI with
valid split BTF. These offline facts do not qualify 620 display or NVENC.
The [consolidated preflight](nvidia620-staging-preflight-20261118.json), run by
[`check-nvidia620-staging-inputs.py`](../../scripts/check-nvidia620-staging-inputs.py),
rechecked both archive signatures, all four pinned package hashes and
versioned dependencies, all 13 module versions/vermagic/split BTF, the
running 615 boundary and 839,901,184 free EFI bytes. It passed without
installing or loading 620.
A [fakeroot Pacman transaction simulation](nvidia620-pacman-db-transaction-20261118.json)
then copied the live local and sync databases to a temporary root, removed
the six version-bound 615 driver packages from that copy, and installed the
four pinned 620 archives with `--dbonly --noscriptlet`. Pacman accepted the
dependency transaction and the copied database ended with matched 620
packages while the live 615 package versions stayed unchanged. This is a
database-only check; it does not prove file conflict resolution, hook safety,
module placement, the UKI or a boot. The repeatable simulator is
[`simulate-nvidia620-pacman-transaction.py`](../../scripts/simulate-nvidia620-pacman-transaction.py).
A separate [file-path collision audit](nvidia620-file-collisions-20261118.json)
reads all four archive manifests and the live Pacman ownership database:
4,281 distinct candidate files, 180 expected replacements owned only by the
615 packages scheduled for removal or `nvidia-utils`, and zero collisions
among the new archives, with other installed packages, or with existing
unowned files. The [audit script](../../scripts/check-nvidia620-file-collisions.py)
is read-only. The later native-root stage below completed the actual
candidate extraction gate.
A [full-payload fakeroot transaction](nvidia620-pacman-payload-transaction-20261118.json)
now uses the simulator's `--extract-payload` mode to remove the six 615
driver packages from a copied package database and extract all four pinned
620 archives into a disposable partial root. All 4,281 non-directory archive
entries were present afterward; the 13 kernel38 modules were present, and
`pacman -Qkk` reported zero altered files for every new package. Live 615
package versions stayed unchanged. Pacman emitted 245 expected warnings
about old 615 files absent from the partial root; it emitted no other stderr.
The normal database-only mode still passes. This extends the offline gate to
real package payload extraction. This disposable check was not itself an
installation into the Btrfs candidate snapshot; the later native-root stage
completed snapshot replacement and UKI build. Module load and boot remain
untested on 620.
A second [disposable transaction using Pacman's guest-system `--sysroot`
option](nvidia620-pacman-sysroot-transaction-20261118.json) also passed:
all four 620 packages have matching versions, all 4,281 archive file entries
and 13 modules are present, and `pacman -Qkk` reports zero altered files.
It leaves live 615 versions unchanged and emits no Pacman stderr. The partial
test root uses a minimal Pacman configuration with signature checking disabled;
the separate signed-archive preflight remains the signature gate. This test
exercises the Pacman mode intended for the eventual mounted Btrfs candidate,
but did not exercise the actual snapshot, its full config or its UKI; the
native-root staging results below now cover those separate gates.

The running `@` root, its NVIDIA 615 packages, the existing kernel36/37/38
UKIs and Limine default are the rollback path. A candidate must never
replace those files or change the running root's package database. Before
any candidate installation, record their package and UKI hashes, BootOrder,
and free space; after staging, compare all of them again. A candidate UKI
gets a distinct filename and direct UEFI entry. Do not set BootNext while
staging.

## Candidate preparation, without booting

The [snapshot staging helper](../../scripts/stage-nvidia620-snapshot.py)
performs a read-only preflight by default. It verifies that `/` is Btrfs
subvolume `@`, the current kernel is 38 with NVIDIA 615 packages, `/boot` is
the separate VFAT partition, and Limine is first in BootOrder. Its
[19 November receipt](nvidia620-candidate-snapshot-20261119.json) records
a passing root-only stage: live `@` is ID 256, candidate `@nvidia620` is
ID 268, and EFI hashes, BootOrder, packages and boot ID were unchanged.
That mode takes an exclusive Pacman lock,
mounts the Btrfs top level at a private `/run` path, creates `@nvidia620`
only if absent, checks distinct subvolume IDs and the copied package database,
removes the **copied** Pacman lock from the candidate while retaining the live
lock, unmounts safely, and compares EFI hashes, BootOrder, package versions and
boot ID. Failed unmounts leave the private mountpoint intact for inspection;
the helper never recursively removes a mounted filesystem. It does not
install 620 packages, write EFI files, set BootNext or reboot.

The [candidate package-stage helper](../../scripts/stage-nvidia620-packages.py)
now has a read-only default plan and a root-only `--stage` mode for an
**existing** `@nvidia620` snapshot. It rechecks pinned archive hashes and
the signed-archive/module/EFI preflight, takes the host Pacman lock, mounts
only the candidate at a private `/run` path, and verifies that its database
is still 615 and its `/boot` is not mounted. It refuses package-owned hooks
before masking both candidate hook directories; the isolated `pacman
--sysroot` removal/install runs with scriptlets disabled. It then checks
candidate package files with `pacman -Qkk`, requires the 13 packaged kernel38 modules and
runs `depmod -b` for the candidate. Finally it unmounts safely and compares
the live package versions, EFI hashes, BootOrder and boot ID against the
pre-stage state. It does not create a UKI, set a boot entry or reboot.
The helper's read-only plan, unprivileged refusal and privileged stage have
all been checked.

The first [package-stage receipt](nvidia620-candidate-packages-20261119.json)
records successful removal of six 615 packages and installation of all four
620 archives in the candidate, with zero altered files. Its final gate failed
because it counted every `*.ko` in the copied kernel tree. The
[first read-only resumption](nvidia620-candidate-packages-resumed-20261119.json)
still failed after narrowing the count to `updates/dkms`: the copied root
also contains the pre-existing, unowned `cpuid.ko`. The checker now compares
the exact 13 module names from the verified package archive, accepts only
that additional `cpuid.ko` when byte-identical to the live file, and records
it explicitly. The [final package receipt](nvidia620-candidate-packages-verified-20261119.json)
passes `pacman -Qkk`, module identity and candidate `depmod` without
reinstalling packages. All three receipts report unchanged live packages,
EFI hashes, BootOrder and boot ID.

The [candidate UKI receipt](nvidia620-candidate-uki-20261119.json) records a
successful `mkinitcpio --nopost` build inside `@nvidia620`, the candidate
platform verifier, four embedded 620 NVIDIA modules, the exact kernel38
payload and the checked `@nvidia620` root/audio command line. Its SHA256 is
`6a625780543ab527f02ce40b7afb8343f9c54ac3f7dc82f1ae4f9375d62e15d2`.
The image was built outside EFI first. The [EFI-stage receipt](nvidia620-candidate-efi-20261119.json)
records the same image at `EFI/Linux/p16_nvidia620_kernel38.efi` and direct
UEFI entry `Boot0004`. `BootOrder` remains `0002,0001,2001,2002,2003`,
`BootNext` remains absent, the live root remains `@`/615, and no reboot was
performed. Native 620 operation is still unqualified.

1. Mount the Btrfs top level (`subvolid=5`) at a private root-only directory
   and take a writable point-in-time snapshot of `@` named `@nvidia620`.
   Mount that snapshot at a second private directory. Verify its Btrfs
   subvolume ID differs from 256 and that package operations resolve to its
   own `/var/lib/pacman`, never `/var/lib/pacman` on the running root. The
   separate home, log and pacman-cache subvolumes stay unmounted there.
2. Keep the candidate's `/boot` unmounted during package transactions. Use
   `pacman --sysroot` with the hash-checked local archives passed by absolute
   host path; Pacman does not rewrite package target paths for `--sysroot`. Mask
   both candidate ALPM hook directories during the transaction so generic
   DKMS/mkinitcpio and Limine hooks cannot touch shared EFI state; restore
   the directories afterward. Disable package scriptlets for the isolated
   transaction and run all required build/verification steps explicitly.
3. Remove only from the candidate the four version-bound 615 driver packages
   (`linux-p16-platform-{34,36,37,38}-drivers`), `nvidia-open-dkms` 615 and
   `n1x-nvidia-drm-fix` 615. Install signed `nvidia-utils` and
   `nvidia-open-dkms` 620, the pinned 620 DKMS patch package, and
   `linux-p16-platform-38-drivers-nvidia620`. Confirm package ownership and
   hashes for all 13 kernel38 production modules, `modinfo` version and
   `vermagic`, firmware files and matched 620 userspace. The old and alternate
   driver packages own the same `updates/dkms` paths, so removal followed by
   install must leave exactly one file per module. Run `depmod` explicitly
   for kernel38 before image construction because ALPM hooks were masked.
   No host module is installed or loaded during this step.
   On a new candidate snapshot, run the prepared helper with a new receipt
   path. The current `@nvidia620` snapshot already contains 620; do not run
   the install mode again on it. The recorded recovery used `--resume-from`
   with the first failed receipt and a new output path:

   ```sh
   pkexec --disable-internal-agent /usr/bin/python3 \
     /home/johann/p16/p16rtx_linux/scripts/stage-nvidia620-packages.py \
     --stage --output /home/johann/p16/p16rtx_linux/docs/evidence/nvidia620-candidate-packages-NEW.json
   ```
4. Build a candidate kernel38 UKI from the snapshot with its
   installed `mkinitcpio` configuration and exact kernel release. Start from
   the verified audio-enabled kernel38 UKI and derive its candidate command
   line with [`prepare-nvidia620-cmdline.py`](../../scripts/prepare-nvidia620-cmdline.py).
   It replaces only `rootflags=subvol=@` with
   `rootflags=subvol=@nvidia620`, requiring exactly one replacement and
   preserving the DSP flags and SOF blacklist.
   Check embedded kernel, initramfs 620 modules, SPI HID bytes, BTF and ACPI
   policy with the candidate root's platform verifier. Verify the UKI
   command line independently with
   `verify-dsp-boot-cmdline.py --root-subvolume @nvidia620` before copying it
   to a **new** EFI filename. That verifier rejects both a lingering
   `rootflags=subvol=@` token and duplicate rootflags.
   The [candidate UKI staging helper](../../scripts/stage-nvidia620-uki.py)
   now performs this build in a privately mounted candidate root. It requires
   the passing package-stage receipt, checks the source kernel38/615 UKI and
   DSP flags, runs `mkinitcpio --nopost` inside `@nvidia620`, then checks the
   resulting 620 module payload, platform verifier and exact candidate root
   command line. It publishes the verified image and a receipt to a **new
   directory outside EFI**. Its privileged mode passed on 19 November with
   the verified package receipt. A repeat would require a new output
   directory:

   ```sh
   pkexec --disable-internal-agent /usr/bin/python3 \
     /home/johann/p16/p16rtx_linux/scripts/stage-nvidia620-uki.py \
     --package-receipt /home/johann/p16/p16rtx_linux/docs/evidence/nvidia620-candidate-packages-NEW.json \
     --output-dir /home/johann/p16/nvidia620-uki-stage-NEW
   ```

   A build or verification failure leaves EFI and BootNext untouched. A
   private unmount failure leaves its `/run` mountpoint intact for inspection
   rather than recursively removing a mounted snapshot.
5. Check that the copied UKI fits the EFI partition and has the same SHA256
   as the verified candidate. Create a direct UEFI entry for that distinct
   filename, preserving Limine first and kernel36 as the default. Record the
   final BootOrder and all rollback hashes. Remove temporary mounts cleanly.
   The [EFI stage helper](../../scripts/stage-nvidia620-efi.py) requires the
   passing UKI receipt and matching live rollback hashes, verifies the
   candidate subvolume still exists with the same 620 packages, kernel and
   NVIDIA module hashes, then copies the exact image to a new EFI filename.
   `efibootmgr -C` creates an active entry **outside BootOrder**;
   the helper checks that Limine's order and BootNext stay unchanged and
   records the result. This root-only mode passed on 19 November. A repeat
   must use new output and EFI paths and must follow fresh passing receipts:

   ```sh
   pkexec --disable-internal-agent /usr/bin/python3 \
     /home/johann/p16/p16rtx_linux/scripts/stage-nvidia620-efi.py \
     --uki-stage-dir /home/johann/p16/nvidia620-uki-stage-NEW \
     --output /home/johann/p16/p16rtx_linux/docs/evidence/nvidia620-candidate-efi-NEW.json
   ```

   This does not select a next boot. The resulting UEFI entry is available
   for one attended 620 qualification session.

Any failed package, hash, command-line or image check stops before EFI entry
creation. The candidate snapshot can then be discarded without affecting
the running root. The direct-boot entry is staged only after every offline
gate passes.

Repeat the disposable payload check with:

```sh
fakeroot -- python3 scripts/simulate-nvidia620-pacman-transaction.py \
  --extract-payload --output NEW_JSON_PATH
fakeroot -- python3 scripts/simulate-nvidia620-pacman-transaction.py \
  --extract-payload --sysroot-mode --output ANOTHER_NEW_JSON_PATH
```

## One attended native qualification session

The [both-host UVC trace](n1x-media-20261118/uvc-dma-both-hosts-kernel38.md)
passes on the current kernel38/615 boot. The audio-enabled kernel38/615 UKI
passed the source-image check during candidate UKI construction. Its DSP
parameters are preserved in the verified 620 UKI, so a separate 615 boot is
not a prerequisite for testing audio on 620.

Use one attended boot of the fully staged `@nvidia620` candidate. In that
session, check root and module identities, GPU/display, ADSP audio playback
and capture, internal RGB/IR and external UVC capture, CUDA and OpenGL,
H.264/HEVC/AV1 NVENC session probes and independently decoded output,
an installed application recording, and physical suspend/resume followed
by the same essential device and application checks. Collect the complete
results before changing any image or package. A separate 615 boot is only
justified by a concrete 620 finding that needs an A/B comparison; record that
reason first. If the candidate fails to boot, the existing Limine/kernel36
root-`@` path is the rollback. No package repair is required on that root.
