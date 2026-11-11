#!/usr/bin/env python3
"""Validate explicit legacy/native ACPI initramfs profiles; never change firmware."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import stat

REFERENCE_SSDT = 'kernel/firmware/acpi/SSDT.aml'
REFERENCE_SHA256 = '9b28ffc14c19f8b7ea2278de88ff9ec070f5f70401107d81fef067a916aa9695'
ACPI_DIR = 'kernel/firmware/acpi'
MODES = ('legacy', 'native', 'auto')


def check_files(files, mode):
    if mode not in MODES:
        raise ValueError('Unknown ACPI profile: ' + mode)
    if any(name != REFERENCE_SSDT for name in files):
        raise ValueError('Unexpected ACPI override: ' + ', '.join(sorted(files)))
    if mode == 'auto':
        mode = 'legacy' if files else 'native'
    if mode == 'native':
        if files:
            raise ValueError('Native ACPI profile contains an override')
    elif set(files) != {REFERENCE_SSDT} or \
            hashlib.sha256(files[REFERENCE_SSDT]).hexdigest() != REFERENCE_SHA256:
        raise ValueError('Legacy ACPI profile requires the exact reference SSDT')
    return mode


def check_tree(root, mode):
    root = Path(root)
    current = root
    for part in ACPI_DIR.split('/'):
        current /= part
        if current.is_symlink():
            raise ValueError('Symlink in ACPI override path: ' + str(current))
        if current.exists() and not current.is_dir():
            raise ValueError('Non-directory ACPI override path: ' + str(current))
    files = {}
    for path in current.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('Non-regular ACPI override: ' + str(path))
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return check_files(files, mode)


def early_archives(data):
    """Return complete newc archives and the untouched compressed/main tail."""
    offset, archives = 0, []
    while data[offset:offset + 6] in (b'070701', b'070702'):
        records = []
        while True:
            start = offset
            if len(data) - offset < 110 or data[offset:offset + 6] not in (b'070701', b'070702'):
                raise ValueError('Truncated or malformed early CPIO header')
            try:
                fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16)
                          for i in range(13)]
            except ValueError as error:
                raise ValueError('Invalid early CPIO numeric field') from error
            size, namesize = fields[6], fields[11]
            name_start = offset + 110
            name_end = name_start + namesize
            if not namesize or name_end > len(data) or data[name_end - 1] != 0:
                raise ValueError('Truncated early CPIO name')
            try:
                name = data[name_start:name_end - 1].decode('utf-8')
            except UnicodeDecodeError as error:
                raise ValueError('Invalid early CPIO name') from error
            if '\0' in name or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                raise ValueError('Unsafe early CPIO name')
            name = str(PurePosixPath(name))
            body = (name_end + 3) & ~3
            end = body + size
            offset = (end + 3) & ~3
            if offset > len(data):
                raise ValueError('Truncated early CPIO body/padding')
            payload = data[body:end]
            if data[start:start + 6] == b'070702' and sum(payload) & 0xffffffff != fields[12]:
                raise ValueError('Invalid early CPIO checksum')
            records.append((name, fields[1], payload, data[start:offset]))
            if name == 'TRAILER!!!':
                if size:
                    raise ValueError('Invalid early CPIO trailer')
                break
        archives.append(records)
        while offset < len(data) and data[offset] == 0:
            offset += 1
    return archives, data[offset:]


def without_reference_ssdt(data):
    archives, tail = early_archives(data)
    files = {}
    for records in archives:
        for name, mode, body, raw in records:
            if name == ACPI_DIR or name.startswith(ACPI_DIR + '/'):
                if stat.S_ISDIR(mode):
                    continue
                if name in files or not stat.S_ISREG(mode):
                    raise ValueError('Duplicate or non-regular early ACPI override')
                files[name] = body
    check_files(files, 'legacy')
    rebuilt = bytearray()
    for records in archives:
        for name, mode, body, raw in records:
            if name != REFERENCE_SSDT:
                rebuilt.extend(raw)
        rebuilt.extend(bytes(-len(rebuilt) % 512))
    rebuilt.extend(tail)
    result = bytes(rebuilt)
    # No extraction/recompression: every retained record and main tail stays identical.
    new_archives, new_tail = early_archives(result)
    kept = [r for records in archives for r in records if r[0] != REFERENCE_SSDT]
    if [r for records in new_archives for r in records] != kept or new_tail != tail:
        raise ValueError('Unexpected change to retained initramfs content')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--mode', choices=MODES, default='legacy')
    args = parser.parse_args()
    try:
        print('ACPI initramfs profile valid: ' + check_tree(args.tree, args.mode))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
