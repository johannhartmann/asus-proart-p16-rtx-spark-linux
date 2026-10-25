#!/usr/bin/env python3
"""Prepare and verify P16 touchpad policy and OEM speaker tuning.

Firmware is downloaded and extracted, never executed or redistributed.
Live writes are allowed only inside the kernel installer's backup transaction.
"""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import urllib.request

REPO = Path(__file__).resolve().parents[1]
QUIRKS = '/etc/libinput/local-overrides.quirks'
INITCPIO = '/etc/mkinitcpio.conf.d/zz-p16-speakers.conf'
FIRMWARE_DIR = '/usr/lib/firmware/cirrus'
FIRMWARE_NAMES = (
    'cs35l56-b0-dsp1-misc-10431484-spkid0.wmfw',
    'cs35l56-b0-dsp1-misc-10431484-spkid0-l1u0.bin',
    'cs35l56-b0-dsp1-misc-10431484-spkid0-l1u1.bin',
)
PATHS = [QUIRKS, INITCPIO] + [f'{FIRMWARE_DIR}/{name}' for name in FIRMWARE_NAMES]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def manifest():
    data = json.loads((REPO / 'config/speaker-firmware.json').read_text())
    require(tuple(row['name'] for row in data['files']) == FIRMWARE_NAMES,
            'Unexpected firmware destinations')
    return data


def verify(data, row):
    require(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'],
            'Size/SHA-256 mismatch: ' + row.get('name', 'ASUS archive'))
    return data


def atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.p16-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(directory):
    lock = manifest()
    spec = lock['archive']
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / 'asus-audio.exe'
    if archive.exists():
        data = verify(archive.read_bytes(), spec)
    else:
        with urllib.request.urlopen(spec['url'], timeout=60) as response:
            data = verify(response.read(spec['bytes'] + 1), spec)
        atomic_write(archive, data)
    # The verified executable contains a 7z archive at this exact byte offset.
    # Extract explicit members to stdout: no archive-controlled filesystem paths.
    with tempfile.TemporaryDirectory(prefix='.extract-', dir=directory) as temporary:
        payload = Path(temporary) / 'payload.7z'
        payload.write_bytes(data[spec['offset']:])
        outputs = {}
        for row in lock['files']:
            result = subprocess.run(['bsdtar', '-xOf', str(payload), row['member']],
                                    check=True, capture_output=True, timeout=60)
            outputs[row['name']] = verify(result.stdout, row)
    for name, content in outputs.items():
        atomic_write(directory / name, content)
    print(f'Verified {len(outputs)} firmware files in {directory}')


def touchpad_text(current):
    """Preserve other quirks and accept an already installed equivalent match."""
    desired = (REPO / 'config/p16-touchpad.quirks').read_text()
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(current)
    expected = configparser.ConfigParser(interpolation=None)
    expected.read_string(desired)
    section = expected.sections()[0]
    values = dict(expected[section])
    found = False
    for name in parser.sections():
        existing = dict(parser[name])
        if existing == values:
            found = True
            continue
        # Do not silently stack a competing P16 pressure policy.
        if name == section or (existing.get('matchvendor', '').lower() == '0x093a'
                              and existing.get('matchproduct', '').lower() == '0x4f01'):
            raise ValueError('Existing P16 touchpad policy differs; reconcile it before installation: ' + name)
    if found:
        return current
    return current + ('\n' if current.endswith('\n') else '\n\n' if current else '') + desired


def plan(directory, root=Path('/')):
    """Validate every input and destination before returning any live writes."""
    files = {}
    files[INITCPIO] = (REPO / 'config/zz-p16-speakers.conf').read_bytes()
    for row in manifest()['files']:
        files[f"{FIRMWARE_DIR}/{row['name']}"] = verify((directory / row['name']).read_bytes(), row)
    quirks = root / QUIRKS.lstrip('/')
    require(not quirks.is_symlink(), 'Refusing a symlink touchpad configuration')
    current = quirks.read_text() if quirks.exists() else ''
    files[QUIRKS] = touchpad_text(current).encode()
    changes = {}
    for name, content in files.items():
        target = root / name.lstrip('/')
        require(not target.is_symlink(), 'Refusing a symlink destination: ' + name)
        if target.exists():
            old = target.read_bytes()
            if name != QUIRKS:
                require(old == content, 'Existing peripheral file differs; refusing overwrite: ' + name)
            if old == content:
                continue
        changes[name] = content
    return changes


def apply(directory, backup):
    import install_state
    require(os.geteuid() == 0, 'Run through sudo scripts/install-kernel.sh')
    check_machine()
    state = install_state.load(install_state.trusted_backup(backup))
    require(state['status'] == 'running' and set(PATHS).issubset(state['files']),
            'A running installer checkpoint covering all peripheral files is required')
    for name, content in plan(directory).items():
        path = Path(name)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        atomic_write(path, content, mode)


def check_machine():
    require(platform.machine() == 'aarch64', 'AArch64 required')
    for key, expected in {'sys_vendor': 'ASUS', 'product_name': 'ProArt P16 H7607BA',
                          'bios_version': 'H7607BA.300'}.items():
        require((Path('/sys/class/dmi/id') / key).read_text().strip() == expected,
                'Unsupported machine: ' + key)


def check_installed():
    check_machine()
    for row in manifest()['files']:
        verify((Path(FIRMWARE_DIR) / row['name']).read_bytes(), row)
    current = Path(QUIRKS).read_text()
    require(touchpad_text(current) == current, 'P16 touchpad quirk is missing')
    print('P16 touchpad policy and all three speaker firmware hashes match.')
    initcpio = Path(INITCPIO)
    if not initcpio.exists() or initcpio.read_bytes() != (REPO / 'config/zz-p16-speakers.conf').read_bytes():
        print('Explicit early-boot firmware inclusion is not configured by this repository yet.')
    print('This verifies installed files, not physical touchpad/audio operation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'check-inputs', 'check-installed', 'apply'])
    parser.add_argument('--directory', type=Path, default=REPO / 'build/speaker-firmware')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            prepare(args.directory)
        elif args.action == 'check-inputs':
            check_machine()
            changes = plan(args.directory)
            print(f'Peripheral inputs verified; {len(changes)} file(s) need installation.')
        elif args.action == 'check-installed':
            check_installed()
        else:
            require(args.backup is not None, '--backup is required')
            apply(args.directory, args.backup)
    except (OSError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
