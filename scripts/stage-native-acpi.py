#!/usr/bin/env python3
"""Stage a verified UKI without the reference SSDT; never install or select it."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import struct
import subprocess
import tempfile

_spec = importlib.util.spec_from_file_location('native_acpi_boot', Path(__file__).with_name('verify-boot.py'))
BOOT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BOOT)
POLICY = BOOT.ACPI_POLICY


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require_unsigned(data, sections):
    pe = struct.unpack_from('<I', data, 60)[0]
    optional = pe + 24
    size = struct.unpack_from('<H', data, pe + 20)[0]
    if optional + size > len(data) or size < 152 or \
            struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected a complete PE32+ optional header')
    # IMAGE_DIRECTORY_ENTRY_SECURITY is a file offset/length, not a section.
    if any(struct.unpack_from('<II', data, optional + 112 + 4 * 8)):
        raise ValueError('Signed UKI: rebuild/re-sign through the trusted signing workflow')
    if sections.get('.pcrsig', b'').strip(b'\0'):
        raise ValueError('PCR-signed UKI: regenerate the measured-boot policy separately')


def default_image(menu=Path('/boot/limine.conf'), boot_root=Path('/boot')):
    text = menu.read_text()
    defaults = re.findall(r'^default_entry:\s*(.*?)\s*$', text, re.M)
    if len(defaults) != 1:
        raise ValueError('Expected exactly one Limine default')
    parents, entries, current = [], {}, None
    for line in text.splitlines():
        if line.lstrip().startswith('#'):
            continue
        heading = re.fullmatch(r'\s*(/+)[+]?([^/].*?)\s*', line)
        if heading:
            level = len(heading[1])
            if level > len(parents) + 1:
                raise ValueError('Invalid Limine hierarchy')
            parents = parents[:level - 1] + [heading[2]]
            current = '/'.join(parents)
            if current in entries:
                raise ValueError('Duplicate Limine entry')
            entries[current] = []
        if current == defaults[0]:
            entries[current].extend(re.findall(r'boot\(\):/EFI/Linux/\S+', line))
    tokens = entries.get(defaults[0], [])
    if len(tokens) != 1:
        raise ValueError('Default must select exactly one hashed Linux UKI')
    match = re.fullmatch(r'boot\(\):(/EFI/Linux/[^#\s]+\.efi)#([0-9a-fA-F]{128})', tokens[0])
    if not match:
        raise ValueError('Default UKI needs a BLAKE2b pin')
    path = (boot_root / match[1].lstrip('/')).resolve()
    if not path.is_relative_to((boot_root / 'EFI/Linux').resolve()) or \
            hashlib.blake2b(path.read_bytes()).hexdigest() != match[2].lower():
        raise ValueError('Default UKI path/hash mismatch')
    return path


def section_layout(data):
    """Record load addresses and flags so objcopy cannot relocate other payloads."""
    pe = struct.unpack_from('<I', data, 60)[0]
    optional = pe + 24
    image_base = struct.unpack_from('<Q', data, optional + 24)[0]
    headers = optional + struct.unpack_from('<H', data, pe + 20)[0]
    result = {}
    for index in range(struct.unpack_from('<H', data, pe + 6)[0]):
        header = headers + index * 40
        name = data[header:header + 8].rstrip(b'\0').decode()
        result[name] = (image_base + struct.unpack_from('<I', data, header + 12)[0],
                        struct.unpack_from('<I', data, header + 36)[0])
    return result


def stage(source, output):
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if output.exists() or any(output.is_relative_to(Path(p)) for p in ('/boot', '/efi')):
        raise ValueError('Choose a new staging directory outside the boot partitions')
    original = source.read_bytes()
    sections = BOOT.sections(source)
    require_unsigned(original, sections)
    layout = section_layout(original)
    BOOT.verify_image(source, acpi_mode='legacy')
    modified = POLICY.without_reference_ssdt(sections['.initrd'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-acpi-', dir=output.parent) as directory:
        work = Path(directory)
        snapshot, initrd, candidate = work / 'source.efi', work / 'initrd', work / 'native-acpi.efi'
        snapshot.write_bytes(original)
        initrd.write_bytes(modified)
        # BFD --update-section can retain the old VirtualSize and omit final
        # file padding when shrinking the last PE section. Re-add the section
        # at the same load address to regenerate both sizes consistently.
        subprocess.run(['objcopy', '--remove-section', '.initrd',
                        '--add-section', '.initrd=' + str(initrd),
                        '--change-section-vma', '.initrd=' + hex(layout['.initrd'][0]),
                        '--set-section-flags', '.initrd=alloc,load,readonly,data',
                        str(snapshot), str(candidate)], check=True, capture_output=True)
        after = BOOT.sections(candidate)
        require_unsigned(candidate.read_bytes(), after)
        if section_layout(candidate.read_bytes()) != layout or \
                set(after) != set(sections) or after['.initrd'] != modified or \
                any(after[name] != data for name, data in sections.items() if name != '.initrd'):
            raise ValueError('Unexpected change to UKI payloads')
        BOOT.verify_image(candidate, acpi_mode='native')
        if source.read_bytes() != original:
            raise ValueError('Source UKI changed while staging')
        report = {
            'prepared_at': datetime.now(timezone.utc).isoformat(),
            'source': str(source), 'source_sha256': digest(original),
            'candidate_sha256': digest(candidate.read_bytes()),
            'source_kernel': sections['.uname'].rstrip(b'\0\n').decode(),
            'running_kernel_at_preparation': os.uname().release,
            'source_acpi_profile': 'legacy', 'candidate_acpi_profile': 'native',
            'removed': POLICY.REFERENCE_SSDT,
            'unchanged_sections': {name: digest(data) for name, data in sections.items() if name != '.initrd'},
            'main_initramfs_tail_sha256': digest(POLICY.early_archives(modified)[1]),
            'installed': False, 'boot_files_written': False, 'default_changed': False,
            'hardware_qualified': False,
        }
        manifest = work / 'manifest.json'
        manifest.write_text(json.dumps(report, indent=2) + '\n')
        # Reserve a new directory atomically; never overwrite a previous artifact.
        output.mkdir(mode=0o700)
        published = []
        try:
            for path in (candidate, manifest):
                target = output / path.name
                os.link(path, target)
                published.append(target)
            if os.geteuid() == 0 and 'PKEXEC_UID' in os.environ:
                owner = pwd.getpwuid(int(os.environ['PKEXEC_UID']))
                for path in (*published, output):
                    os.chown(path, owner.pw_uid, owner.pw_gid)
        except BaseException:
            for path in published:
                path.unlink()
            output.rmdir()
            raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--source', type=Path)
    sources.add_argument('--source-default', action='store_true', help='use the hash-pinned Limine default')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = stage(default_image() if args.source_default else args.source, args.output)
        print('Prepared, not installed: ' + str(args.output / 'native-acpi.efi'))
        print('SHA256: ' + report['candidate_sha256'])
    except (OSError, ValueError, KeyError, struct.error, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
