# Isolated NVIDIA 620 root: staging and qualification boundary

This is the staging procedure for the ASUS ProArt P16 H7607BA, written from
the live kernel38/615 system on 18 November 2026. It is **not** evidence that
620 has been installed or booted. No reboot belongs to the preparation
phase. The machine currently uses a LUKS-backed Btrfs root subvolume `@`
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
is read-only. Actual extraction into the candidate snapshot remains a gate.
A [full-payload fakeroot transaction](nvidia620-pacman-payload-transaction-20261118.json)
now uses the simulator's `--extract-payload` mode to remove the six 615
driver packages from a copied package database and extract all four pinned
620 archives into a disposable partial root. All 4,281 non-directory archive
entries were present afterward; the 13 kernel38 modules were present, and
`pacman -Qkk` reported zero altered files for every new package. Live 615
package versions stayed unchanged. Pacman emitted 245 expected warnings
about old 615 files absent from the partial root; it emitted no other stderr.
The normal database-only mode still passes. This extends the offline gate to
real package payload extraction, but it is **not** an installation into the
Btrfs candidate snapshot. Actual snapshot file replacement, hooks, module
load, UKI and boot remain untested.

The running `@` root, its NVIDIA 615 packages, the existing kernel36/37/38
UKIs and Limine default are the rollback path. A candidate must never
replace those files or change the running root's package database. Before
any candidate installation, record their package and UKI hashes, BootOrder,
and free space; after staging, compare all of them again. A candidate UKI
gets a distinct filename and direct UEFI entry. Do not set BootNext while
staging.

## Candidate preparation, without booting

The [snapshot staging helper](../../scripts/stage-nvidia620-snapshot.py) now
performs a read-only preflight by default. It verifies that `/` is Btrfs
subvolume `@`, the current kernel is 38 with NVIDIA 615 packages, `/boot` is
the separate VFAT partition, and Limine is first in BootOrder. It currently
returns `ready_to_stage: false` while the graphical media-package Pacman
transaction is waiting; it will not take a package-database snapshot during
that transaction. Its root-only `--stage --output NEW_MANIFEST` mode is
prepared but has **not** been run. That mode takes an exclusive Pacman lock,
mounts the Btrfs top level at a private `/run` path, creates `@nvidia620`
only if absent, checks distinct subvolume IDs and the copied package database,
unmounts safely, and compares EFI hashes, BootOrder, package versions and
boot ID. Failed unmounts leave the private mountpoint intact for inspection;
the helper never recursively removes a mounted filesystem. It does not
install 620 packages, write EFI files, set BootNext or reboot.

1. Mount the Btrfs top level (`subvolid=5`) at a private root-only directory
   and take a writable point-in-time snapshot of `@` named `@nvidia620`.
   Mount that snapshot at a second private directory. Verify its Btrfs
   subvolume ID differs from 256 and that package operations resolve to its
   own `/var/lib/pacman`, never `/var/lib/pacman` on the running root. The
   separate home, log and pacman-cache subvolumes stay unmounted there.
2. Keep the candidate's `/boot` unmounted during package transactions. Use
   `pacman --sysroot` with local archives copied inside the candidate. Mask
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
5. Check that the copied UKI fits the EFI partition and has the same SHA256
   as the verified candidate. Create a direct UEFI entry for that distinct
   filename, preserving Limine first and kernel36 as the default. Record the
   final BootOrder and all rollback hashes. Remove temporary mounts cleanly.

Any failed package, hash, command-line or image check stops before EFI entry
creation. The candidate snapshot can then be discarded without affecting
the running root. The direct-boot entry is staged only after every offline
gate passes.

Repeat the disposable payload check with:

```sh
fakeroot -- python3 scripts/simulate-nvidia620-pacman-transaction.py \
  --extract-payload --output NEW_JSON_PATH
```

## Batched native qualification

Finish the pending kernel38/615 audio-UKI and both-host UVC checks first.
Then use one attended kernel38/615 boot to qualify audio, GPU/display,
camera and physical suspend/resume together. A separate attended boot of
the fully staged `@nvidia620` candidate can compare display, module and
firmware identities, audio, physical resume, CUDA and OpenGL NVENC session
probes, H.264/HEVC/AV1 bitstreams with independent decode, and an installed
application recording. Both boot candidates are prepared and checked before
either boot. A failed candidate returns through the existing Limine/kernel36
root-`@` path; no package repair is required on that rollback root.
