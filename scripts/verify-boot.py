#!/usr/bin/env python3
"""Read-only PE/UKI and Limine BLAKE2b verification."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import re
import struct
import subprocess
import tempfile
_policy_spec = importlib.util.spec_from_file_location('p16_acpi_policy', Path(__file__).with_name('acpi_policy.py'))
ACPI_POLICY = importlib.util.module_from_spec(_policy_spec)
_policy_spec.loader.exec_module(ACPI_POLICY)

def sections(path):
    data = Path(path).read_bytes()
    if not data[:2] == b'MZ':
        raise ValueError('Kein PE-Image')
    pe = struct.unpack_from('<I', data, 60)[0]
    if not data[pe:pe + 4] == b'PE\x00\x00':
        raise ValueError('Ungültiger PE-Header')
    machine, count = struct.unpack_from('<HH', data, pe + 4)
    if machine != 0xaa64:
        raise ValueError('Kein ARM64-Image')
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    result = {}
    for i in range(count):
        h = pe + 24 + opt + i * 40
        name = data[h:h + 8].rstrip(b'\x00').decode()
        length, offset = struct.unpack_from('<II', data, h + 16)
        if not offset + length <= len(data):
            raise ValueError('PE-Sektion liegt außerhalb der Datei')
        if name in result:
            raise ValueError('Duplicate PE section: ' + name)
        virtual_size = struct.unpack_from('<I', data, h + 8)[0]
        payload_size = min(length, virtual_size) if virtual_size else length
        result[name] = data[offset:offset + payload_size]
    return result

def verify_image(path, *, acpi_mode="legacy"):
    sec = sections(path)
    release = sec['.uname'].rstrip(b'\x00\n').decode()
    if not re.fullmatch(r'[a-zA-Z0-9._+-]+', release):
        raise ValueError('Invalid kernel release in UKI: ' + release)
    package = subprocess.check_output(
        ['pacman', '-Qoq', '/usr/lib/modules/' + release + '/vmlinuz'], text=True).strip()
    if not package or len(package.splitlines()) != 1:
        raise ValueError('Kernel must have exactly one package owner')
    modules = Path('/usr/lib/modules') / release
    config = (modules / 'build/.config').read_text()
    for option in ['CONFIG_ACPI_WMI=m', 'CONFIG_ASUS_WMI=m', 'CONFIG_ASUS_NB_WMI=m', 'CONFIG_SPI_HID_ACPI=m']:
        if not option in config.splitlines():
            raise ValueError(option)
    image = (modules / 'vmlinuz').read_bytes()
    if not sec['.linux'][:len(image)] == image:
        raise ValueError('Falscher Kernel im UKI')
    cmd = sec['.cmdline'].rstrip(b'\x00').decode()
    if not 'acpi_osi="!Windows 2022"' in cmd:
        raise ValueError('ACPI-OSI-Option fehlt im UKI')
    if not ('console=tty0' in cmd and 'acpi=nospcr' in cmd):
        raise ValueError('N1X-Konsolenoptionen fehlen im UKI')
    if re.search(r'(?:^|\s)acpi=(?:off|noirq)(?:\s|$)', cmd):
        raise ValueError('Unzulässige ACPI-Deaktivierung im UKI')
    data = sec['.initrd']
    with tempfile.TemporaryDirectory(prefix='p16-acpi-verify-') as directory:
        directory = Path(directory)
        initrd = directory / 'initrd'
        initrd.write_bytes(data)
        tree = directory / 'tree'
        tree.mkdir()
        subprocess.run(['lsinitcpio', '-x', str(initrd)], cwd=tree,
                       check=True, stdout=subprocess.DEVNULL)
        resolved_mode = ACPI_POLICY.check_tree(tree, acpi_mode)
    if resolved_mode == 'legacy':
        symbols = (modules / 'build/System.map').read_text()
        if not re.search(' T arch_alloc_acpi_tables$', symbols, re.M):
            raise ValueError('ARM64-ACPI-Allocator fehlt')
        if 'CONFIG_ACPI_TABLE_UPGRADE=y' not in config.splitlines():
            raise ValueError('CONFIG_ACPI_TABLE_UPGRADE=y')
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(data)
        tmp.flush()
        listing = subprocess.check_output(['lsinitcpio', '--list', tmp.name], text=True)
    for module in ['nvidia.ko', 'nvidia-drm.ko', 'hid-asus.ko', 'spi-hid-acpi.ko', 'i2c-mt65xx.ko', 'i2c-hid-acpi.ko']:
        if not '/' + module in listing:
            raise ValueError('Modul fehlt: ' + module)
    for name in ['vfat', 'autofs4', 'zram', 'nvidia', 'nvidia_drm', 'spi_hid_acpi', 'hid_asus', 'wmi', 'asus_wmi', 'asus_nb_wmi']:
        deps = subprocess.check_output(['modprobe', '-S', release, '--show-depends', name], text=True)
        for line in deps.splitlines():
            if line.startswith('insmod '):
                if not Path(line.split()[1]).is_file():
                    raise ValueError(line)
        if not subprocess.check_output(['modinfo', '-k', release, '-F', 'vermagic', name], text=True).split()[0] == release:
            raise ValueError('Falsche Modulversion: ' + name)
    owner = subprocess.check_output(
        ['pacman', '-Qoq', '/usr/lib/modules/' + release + '/vmlinuz'], text=True).strip()
    if owner != package:
        raise ValueError(f'Kernelimage gehört {owner}, erwartet wurde {package}')
    print('UKI, ACPI profile (' + resolved_mode + ') and module dependencies valid:', path)

def verify_menu(config_path=Path('/boot/limine.conf'), boot_root=Path('/boot'), *, acpi_mode='legacy'):
    config = config_path.read_text()
    defaults = re.findall(r'^default_entry:\s*(.*?)\s*$', config, re.M)
    if len(defaults) != 1:
        raise ValueError('Expected exactly one default_entry')
    entries = {}
    parents = []
    current = None
    for line in config.splitlines():
        if line.lstrip().startswith('#'):
            continue
        heading = re.fullmatch(r'\s*(/+)[+]?([^/].*?)\s*', line)
        if heading:
            level, title = len(heading[1]), heading[2]
            if level > len(parents) + 1:
                raise ValueError('Invalid menu hierarchy')
            parents = parents[:level - 1] + [title]
            current = '/'.join(parents)
            if current in entries:
                raise ValueError('Duplicate menu entry: ' + current)
            entries[current] = []
        for token in re.findall(r'boot\(\):/EFI/Linux/\S+', line):
            match = re.fullmatch(r'boot\(\):(/EFI/Linux/[^#\s]+\.efi)#([0-9a-fA-F]{128})', token)
            if match is None:
                raise ValueError('EFI-Eintrag ohne gültigen BLAKE2b-Hash: ' + token)
            path, pin = match.groups()
            image = boot_root / path.lstrip('/')
            if not image.resolve().is_relative_to((boot_root / 'EFI/Linux').resolve()):
                raise ValueError('EFI-Pfad außerhalb von EFI/Linux: ' + path)
            if hashlib.blake2b(image.read_bytes()).hexdigest() != pin.lower():
                raise ValueError('EFI-Hash stimmt nicht: ' + path)
            if current is None:
                raise ValueError('EFI image has no menu entry')
            entries[current].append(image)
    selected = entries.get(defaults[0], [])
    if len(selected) != 1:
        raise ValueError('Default must select exactly one Linux image')
    verify_image(selected[0], acpi_mode=acpi_mode)
    recovery = entries.get('Omarchy-P16-Recovery', [])
    if len(recovery) != 1:
        raise ValueError('P16 recovery entry missing or ambiguous')
    if recovery != selected:
        verify_image(recovery[0], acpi_mode='auto')
    for key, expected in [('quiet', 'no'), ('timeout', '5')]:
        values = re.findall(r'^' + key + r':\s*(.*?)\s*$', config, re.M)
        if values != [expected]:
            raise ValueError('Limine benötigt genau einmal ' + key + ': ' + expected)
    print('Limine menu and Linux image hashes valid')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    primary = Path('/boot/EFI/Linux/omarchy_p16.efi')
    parser.add_argument('--image', type=Path, default=primary)
    parser.add_argument('--image-only', action='store_true')
    parser.add_argument('--acpi-mode', choices=ACPI_POLICY.MODES, default='legacy')
    args = parser.parse_args()
    try:
        verify_image(args.image, acpi_mode=args.acpi_mode)
        if not args.image_only:
            verify_menu(acpi_mode=args.acpi_mode)
    except (ValueError, OSError, KeyError, struct.error, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Boot-Prüfung fehlgeschlagen: ' + str(error) + '\n')
