#!/usr/bin/env python3
"""Install one verified native-ACPI test entry, preserving default and recovery."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tempfile

SPEC = importlib.util.spec_from_file_location('native_acpi_stage', Path(__file__).with_name('stage-native-acpi.py'))
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)
TITLE = 'Omarchy-P16-Native-ACPI-Test'
IMAGE = 'p16-native-acpi-test.efi'


def install(candidate_dir, boot_root=Path('/boot')):
    candidate_dir = Path(candidate_dir).resolve()
    candidate = candidate_dir / 'native-acpi.efi'
    manifest = json.loads((candidate_dir / 'manifest.json').read_text())
    record = candidate_dir / 'installation.json'
    if record.exists() or record.is_symlink():
        raise ValueError('Installation record already exists; refusing replacement')
    data = candidate.read_bytes()
    if STAGE.digest(data) != manifest['candidate_sha256']:
        raise ValueError('Candidate differs from its staging manifest')
    menu = boot_root / 'limine.conf'
    original = menu.read_bytes()
    source = STAGE.default_image(menu, boot_root)
    source_data = source.read_bytes()
    if STAGE.digest(source_data) != manifest['source_sha256']:
        raise ValueError('Default UKI changed since staging; prepare a new candidate')
    STAGE.BOOT.verify_menu(menu, boot_root)
    before, after = STAGE.BOOT.sections(source), STAGE.BOOT.sections(candidate)
    STAGE.require_unsigned(source_data, before)
    STAGE.require_unsigned(data, after)
    command = before['.cmdline'].rstrip(b'\0\n').decode()
    if re.search(r'(?:^|\s)n1x[_-]adsp\.(?:auto_boot|enable_boot)=(?:1|y|yes|true)(?:\s|$)',
                 command, re.I):
        raise ValueError('Choose a baseline without experimental DSP startup')
    if before.keys() != after.keys() or \
            any(after[name] != value for name, value in before.items() if name != '.initrd') or \
            after['.initrd'] != STAGE.POLICY.without_reference_ssdt(before['.initrd']) or \
            STAGE.section_layout(data) != STAGE.section_layout(source_data):
        raise ValueError('Candidate must differ only by reference SSDT removal')
    STAGE.BOOT.verify_image(candidate, acpi_mode='native')
    destination = boot_root / 'EFI/Linux' / IMAGE
    if destination.exists() or destination.is_symlink() or \
            re.search(r'^\s*/\+?' + re.escape(TITLE) + r'\s*$', original.decode(), re.M):
        raise ValueError('Native ACPI test entry/image already exists; refusing replacement')
    pin = hashlib.blake2b(data).hexdigest()
    entry = (f'/{TITLE}\n    protocol: efi\n'
             f'    path: boot():/EFI/Linux/{IMAGE}#{pin}\n').encode()
    updated = original + (b'\n' if original.endswith(b'\n') else b'\n\n') + entry
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = boot_root / ('limine.conf.before-native-acpi-test-' + stamp)
    with backup.open('xb') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    committed = False
    created = False
    temporary = None
    try:
        with destination.open('xb') as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        STAGE.BOOT.verify_image(destination, acpi_mode='native')
        descriptor, name = tempfile.mkstemp(prefix='.limine-native-', dir=boot_root)
        temporary = Path(name)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, menu.stat().st_mode & 0o777)
        STAGE.BOOT.verify_menu(temporary, boot_root)
        if menu.read_bytes() != original or source.read_bytes() != source_data:
            raise ValueError('Boot files changed during installation')
        os.replace(temporary, menu)
        committed = True
        STAGE.BOOT.verify_menu(menu, boot_root)
        report = {'installed_at': datetime.now(timezone.utc).isoformat(),
                  'entry': TITLE, 'image': str(destination), 'image_sha256': STAGE.digest(data),
                  'source': str(source), 'source_kernel': manifest['source_kernel'],
                  'menu_backup': str(backup), 'default_changed': False,
                  'hardware_qualified': False}
        with record.open('x') as stream:
            stream.write(json.dumps(report, indent=2) + '\n')
        if os.geteuid() == 0 and 'PKEXEC_UID' in os.environ:
            owner = pwd.getpwuid(int(os.environ['PKEXEC_UID']))
            os.chown(record, owner.pw_uid, owner.pw_gid)
        return report
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if created and not committed:
            destination.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, 'Run through graphical pkexec authentication\n')
    try:
        with Path('/run/lock/boot-partition.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            report = install(args.candidate)
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
