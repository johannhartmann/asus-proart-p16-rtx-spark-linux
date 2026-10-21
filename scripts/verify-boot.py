#!/usr/bin/env python3
"""Read-only PE/UKI and Limine BLAKE2b verification."""
import argparse
import hashlib
from pathlib import Path
import re
import struct
import subprocess
import tempfile

RELEASE = '7.2.8-14-omarchy-p16-asus'
PINS = {'DSDT.aml': '80e0ad4a051704003d09029cb600a9814e1cd370ce774b9749dc09d2232b5aaf',
        'SSDT.aml': '9b28ffc14c19f8b7ea2278de88ff9ec070f5f70401107d81fef067a916aa9695'}

def sections(path):
    data = Path(path).read_bytes()
    assert data[:2] == b'MZ', 'Kein PE-Image'
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[pe:pe+4] == b'PE\0\0'
    machine, count = struct.unpack_from('<HH', data, pe+4)
    assert machine == 0xaa64, 'Kein ARM64-Image'
    opt = struct.unpack_from('<H', data, pe+20)[0]
    result = {}
    for i in range(count):
        h = pe + 24 + opt + i*40
        name = data[h:h+8].rstrip(b'\0').decode()
        length, offset = struct.unpack_from('<II', data, h+16)
        assert offset + length <= len(data)
        result[name] = data[offset:offset+length]
    return result

def verify_image(path):
    sec = sections(path)
    assert sec['.uname'].rstrip(b'\0\n').decode() == RELEASE
    modules = Path('/usr/lib/modules') / RELEASE
    symbols = (modules / 'build/System.map').read_text()
    assert re.search(r' T arch_alloc_acpi_tables$', symbols, re.M), 'ARM64-ACPI-Allocator fehlt'
    config = (modules / 'build/.config').read_text()
    for option in ['CONFIG_ACPI_TABLE_UPGRADE=y', 'CONFIG_ACPI_WMI=m', 'CONFIG_ASUS_WMI=m', 'CONFIG_ASUS_NB_WMI=m', 'CONFIG_SPI_HID_ACPI=m']:
        assert option in config.splitlines(), option
    image = (modules / 'vmlinuz').read_bytes()
    assert sec['.linux'][:len(image)] == image, 'Falscher Kernel im UKI'
    cmd = sec['.cmdline'].rstrip(b'\0').decode()
    assert 'acpi_osi="!Windows 2022"' in cmd
    assert 'console=tty0' in cmd and 'acpi=nospcr' in cmd
    assert not re.search(r'(?:^|\s)acpi=(?:off|noirq)(?:\s|$)', cmd)
    # Only inspect the early uncompressed newc archive.
    data = sec['.initrd']; offset = 0; files = {}
    while data[offset:offset+6] in (b'070701', b'070702'):
        fields = [int(data[offset+6+i*8:offset+14+i*8], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        start = offset + 110
        name = data[start:start+namesize-1].decode().removeprefix('./')
        start = (start + namesize + 3) & ~3
        assert start+size <= len(data)
        files[name] = data[start:start+size]
        offset = (start+size+3) & ~3
        if name == 'TRAILER!!!': break
    for name, pin in PINS.items():
        assert hashlib.sha256(files['kernel/firmware/acpi/'+name]).hexdigest() == pin
    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(data); tmp.flush()
        listing = subprocess.check_output(['lsinitcpio', '--list', tmp.name], text=True)
    for module in ['nvidia.ko', 'nvidia-drm.ko', 'hid-asus.ko', 'spi-hid-acpi.ko', 'i2c-mt65xx.ko', 'i2c-hid-acpi.ko']:
        assert '/'+module in listing, 'Modul fehlt: '+module
    for name in ['vfat', 'autofs4', 'zram', 'nvidia', 'nvidia_drm', 'spi_hid_acpi', 'hid_asus', 'wmi', 'asus_wmi', 'asus_nb_wmi']:
        deps = subprocess.check_output(['modprobe', '-S', RELEASE, '--show-depends', name], text=True)
        for line in deps.splitlines():
            if line.startswith('insmod '): assert Path(line.split()[1]).is_file(), line
        assert subprocess.check_output(['modinfo', '-k', RELEASE, '-F', 'vermagic', name], text=True).split()[0] == RELEASE
    assert subprocess.check_output(['pacman', '-Qoq', '/usr/lib/modules/'+RELEASE+'/vmlinuz'], text=True).strip() == 'linux-p16-asus'
    print('UKI, ACPI-Overrides und Modulabhängigkeiten gültig:', path)

def verify_menu():
    config = Path('/boot/limine.conf').read_text()
    count = 0
    for path, pin in re.findall(r'boot\(\):(/EFI/Linux/[^\s#]+\.efi)#([0-9a-fA-F]{128})', config):
        assert hashlib.blake2b(Path('/boot'+path).read_bytes()).hexdigest() == pin.lower(), path
        count += 1
    assert count, 'Keine hashgesicherten EFI-Einträge gefunden'
    assert re.search(r'^quiet: no$', config, re.M)
    assert re.search(r'^timeout: 10$', config, re.M)
    print('Limine-Menü und', count, 'EFI-Hashes gültig')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, default=Path('/boot/EFI/Linux/omarchy_linux-p16-asus.efi'))
    parser.add_argument('--image-only', action='store_true')
    args = parser.parse_args()
    verify_image(args.image)
    if not args.image_only: verify_menu()
