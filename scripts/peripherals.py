#!/usr/bin/env python3
"""Prepare and verify P16 touchpad policy and OEM speaker tuning.

Firmware is downloaded and extracted, never executed or redistributed.
Installed files are owned by the platform policy and firmware packages.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import urllib.request

REPO = Path(__file__).resolve().parents[1]
QUIRKS = '/usr/share/libinput/99-p16.quirks'
INITCPIO = '/etc/mkinitcpio.conf.d/zz-p16-speakers.conf'
FIRMWARE_DIR = '/usr/lib/firmware/cirrus'
FIRMWARE_NAMES = (
    'cs35l56-b0-dsp1-misc-10431484-spkid0.wmfw',
    'cs35l56-b0-dsp1-misc-10431484-spkid0-l1u0.bin',
    'cs35l56-b0-dsp1-misc-10431484-spkid0-l1u1.bin',
)


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


def check_machine(dmi=Path('/sys/class/dmi/id')):
    """Board-specific file audit; firmware hashes, not a BIOS label, identify inputs."""
    require(platform.machine() == 'aarch64', 'AArch64 required')
    for key, expected in {'sys_vendor': 'ASUS', 'product_name': 'ProArt P16 H7607BA'}.items():
        require((dmi / key).read_text().strip() == expected,
                'Unsupported machine: ' + key)


def check_installed():
    check_machine()
    for row in manifest()['files']:
        verify((Path(FIRMWARE_DIR) / row['name']).read_bytes(), row)
    current = Path(QUIRKS).read_text()
    require(current == (REPO / 'config/p16-touchpad.quirks').read_text(),
            'Packaged touchpad quirk differs from the maintained configuration')
    print('P16 touchpad policy and all three speaker firmware hashes match.')
    initcpio = Path(INITCPIO)
    if not initcpio.exists() or initcpio.read_bytes() != (REPO / 'config/zz-p16-speakers.conf').read_bytes():
        print('Explicit early-boot firmware inclusion is not configured by this repository yet.')
    print('This verifies installed files, not physical touchpad/audio operation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'check-installed'])
    parser.add_argument('--directory', type=Path, default=REPO / 'build/speaker-firmware')
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            prepare(args.directory)
        else:
            check_installed()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
