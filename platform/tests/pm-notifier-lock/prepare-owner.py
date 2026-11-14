#!/usr/bin/env python3
"""Build a QEMU-only fixture from the actual patched NVIDIA notifier; never load it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CASES = {
    'normal': ('', False),
    'prepare': (' fail_prepare=1', True),
    'thread': (' fail_thread=1', True),
    'late': (' late_fail=1', True),
    'resume': (' fail_resume=1', False),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=CASES, default='normal')
    args = parser.parse_args()
    source, kernel, out = (p.resolve() for p in (args.source, args.kernel, args.output))
    if 'NVIDIA_VERSION = 615.78.08' not in (source / 'version.mk').read_text():
        parser.error('Requires pristine NVIDIA 615.78.08 source')
    out.mkdir(parents=False, exist_ok=False)
    vendor = out / 'vendor/kernel-open/nvidia'
    vendor.mkdir(parents=True)
    shutil.copy2(source / 'kernel-open/nvidia/nv.c', vendor / 'nv.c')
    patch = ROOT / 'platform/nvidia/nvidia-pm-notifier-owner.patch'
    subprocess.run(['patch', '-p1', '--fuzz=0', '--batch', '-i', str(patch)],
                   cwd=out / 'vendor', check=True)
    code = (vendor / 'nv.c').read_text()
    begin = code.index('/*\n * Keep the suspend gates')
    end = code.index('\nstatic NV_STATUS\nnv_restore_user_channels(', begin)
    (out / 'notifier.inc').write_text(code[begin:end])
    for name in ('Kbuild', 'n1x_pm_notifier_lock.c'):
        shutil.copy2(HERE / name, out / name)
    subprocess.run(['make', '-C', str(kernel), 'M=' + str(out),
                    'KCFLAGS=-DN1X_TEST_WORKER', 'W=1', '-j2', 'modules'], check=True)
    suffix, expected_error = CASES[args.case]
    params = 'run_test=1' + suffix
    subprocess.run(['cc', '-static', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-DRETAIN_GATE=1', '-DPM_EXPECT_ERROR=' + str(int(expected_error)),
                    '-DMODEL_PARAMETERS="' + params + '"',
                    str(HERE / 'init.c'), '-o', str(out / 'init')], check=True)
    listing = ('dir /dev 0755 0 0\nnod /dev/console 0600 0 0 c 5 1\n'
               'dir /sys 0755 0 0\ndir /proc 0755 0 0\n'
               f'file /init {out}/init 0755 0 0\n'
               f'file /model.ko {out}/n1x_pm_notifier_lock.ko 0644 0 0\n')
    (out / 'init.list').write_text(listing)
    with (out / 'init.cpio').open('wb') as stream:
        subprocess.run([str(kernel / 'usr/gen_init_cpio'), str(out / 'init.list')],
                       stdout=stream, check=True)
    manifest = {'case': args.case, 'parameters': params, 'expected_pm_error': expected_error,
                'patch_sha256': digest(patch), 'notifier_sha256': digest(out / 'notifier.inc'),
                'module_sha256': digest(out / 'n1x_pm_notifier_lock.ko'),
                'initramfs_sha256': digest(out / 'init.cpio'),
                'kernel_release': (kernel / 'include/config/kernel.release').read_text().strip(),
                'installed': False, 'host_pm_requested': False}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out / 'manifest.json')


if __name__ == '__main__':
    main()
