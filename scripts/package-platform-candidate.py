#!/usr/bin/env python3
"""Package the already validated production modules for an isolated kernel."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


PRODUCTION = {
    'dsp': ('n1x_adsp.ko',),
    'provider': ('n1x_npu_bootstrap.ko',),
    'pluton': ('n1x_pluton.ko',),
    'scp': ('n1x_scp.ko',),
    'als': ('hid-sensor-als.ko',),
    'sensorhub': ('spi-hid.ko', 'spi-hid-acpi.ko'),
    'hwmon': ('spbm.ko',),
    'nvidia': ('nvidia.ko', 'nvidia-drm.ko', 'nvidia-modeset.ko',
               'nvidia-uvm.ko', 'nvidia-peermem.ko'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(args):
    kernel = args.kernel.resolve(strict=True)
    modules = args.modules.resolve(strict=True)
    output = args.output.absolute()
    if output.exists():
        raise RuntimeError('Output exists; do not replace an earlier package')
    km = json.loads((kernel / 'manifest.json').read_text())
    mm = json.loads((modules / 'manifest.json').read_text())
    job = json.loads((kernel / 'job.json').read_text())
    release = km['expected_release']
    pkgbase = km['package_base']
    pkgver = '7.2.8'
    pkgrel = str(km['pkgrel'])
    if job.get('status') != 'complete' or job.get('exit_code') != 0:
        raise RuntimeError('Kernel build is not complete')
    if mm['kernel_release'] != release or Path(mm['kernel_candidate']) != kernel:
        raise RuntimeError('Module set belongs to a different kernel')
    if not mm.get('source_hashes_still_match') or not mm.get('drivers'):
        raise RuntimeError('Module set lacks completed source and BTF validation')
    if mm['nvidia_version'] != '615.78.08':
        raise RuntimeError('Review NVIDIA dependency before packaging a new version')
    if pkgbase != f'linux-p16-platform-{pkgrel}':
        raise RuntimeError('Unexpected kernel package base')
    for name, expected in km['packages'].items():
        if sha(kernel / name) != expected:
            raise RuntimeError('Kernel package changed: ' + name)
    tree = kernel / 'kernel/src/linux-7.2.8'
    image = tree / 'arch/arm64/boot/Image'
    output.mkdir(parents=True, mode=0o700)
    hashes = {}
    for component, names in PRODUCTION.items():
        build = mm['builds'][component]
        if build['exit_code'] != 0:
            raise RuntimeError('Module build failed: ' + component)
        for name in names:
            record = build['modules'][name]
            source = Path(record['path'])
            if source.is_symlink() or not source.is_file() or sha(source) != record['sha256']:
                raise RuntimeError('Module changed: ' + name)
            vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic', str(source)], text=True).split()[0]
            if vermagic != release:
                raise RuntimeError('Module vermagic mismatch: ' + name)
            shutil.copy2(source, output / name)
            hashes[name] = record['sha256']
    license_source = modules / 'nvidia/COPYING'
    shutil.copy2(license_source, output / 'LICENSE.nvidia')
    hashes['LICENSE.nvidia'] = sha(output / 'LICENSE.nvidia')
    provenance = {
        'kernel_release': release, 'kernel_image_sha256': sha(image),
        'kernel_packages': km['packages'], 'kernel_source_commit': km['source_commit'],
        'module_source_commit': mm['source_commit'],
        'npu_source_commit': mm['npu_source_commit'],
        'npu_snapshot_sha256': mm['npu_snapshot_sha256'],
        'hwmon_source_commit': mm['hwmon_source_commit'],
        'hwmon_patch_sha256': mm['hwmon_patch_sha256'],
        'nvidia_version': mm['nvidia_version'], 'module_sha256': dict(hashes),
        'btf_validated': True, 'installed': False, 'hardware_qualified': False,
    }
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    hashes['provenance.json'] = sha(output / 'provenance.json')
    sources = list(hashes)
    recipe = f"""pkgname={pkgbase}-drivers
pkgver={pkgver}
pkgrel={pkgrel}
pkgdesc='Matched RTX Spark kernel{pkgrel} driver bundle'
arch=('aarch64')
license=('GPL-2.0-only' 'MIT')
depends=('{pkgbase}={pkgver}-{pkgrel}' 'nvidia-utils=615.78.08')
options=('!strip' '!debug')
source=({' '.join(repr(name) for name in sources)})
sha256sums=({' '.join(repr(hashes[name]) for name in sources)})

package() {{
  local module
  for module in "$srcdir"/*.ko; do
    install -Dm644 "$module" "$pkgdir/usr/lib/modules/{release}/updates/dkms/${{module##*/}}"
  done
  install -Dm644 "$srcdir/provenance.json" "$pkgdir/usr/share/doc/$pkgname/provenance.json"
  install -Dm644 "$srcdir/LICENSE.nvidia" "$pkgdir/usr/share/licenses/$pkgname/LICENSE.nvidia"
}}
"""
    (output / 'PKGBUILD').write_text(recipe)
    env = dict(os.environ, PKGDEST=str(output))
    with (output / 'build.log').open('w') as stream:
        subprocess.run(['makepkg', '--force', '--noconfirm', '--nodeps'], cwd=output,
                       env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
    candidates = list(output.glob(f'{pkgbase}-drivers-{pkgver}-{pkgrel}-aarch64.pkg.tar.*'))
    if len(candidates) != 1:
        raise RuntimeError('Expected one driver package')
    archive = candidates[0]
    info = subprocess.check_output(['bsdtar', '-xOf', str(archive), '.PKGINFO'], text=True)
    if f'pkgname = {pkgbase}-drivers' not in info or f'pkgver = {pkgver}-{pkgrel}' not in info:
        raise RuntimeError('Unexpected package metadata')
    for name in PRODUCTION.values():
        for module in name:
            archived = subprocess.check_output(['bsdtar', '-xOf', str(archive),
                                                f'usr/lib/modules/{release}/updates/dkms/{module}'])
            if hashlib.sha256(archived).hexdigest() != hashes[module]:
                raise RuntimeError('Packaged module changed: ' + module)
    receipt = {'package': archive.name, 'package_sha256': sha(archive),
               'kernel_release': release, 'modules': 13,
               'provenance_sha256': hashes['provenance.json']}
    (output / 'package-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--modules', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Build as the workspace owner')
    try:
        package(args)
    except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
