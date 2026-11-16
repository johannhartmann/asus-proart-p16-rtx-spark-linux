#!/usr/bin/env python3
"""Extract pinned UVM PM callbacks into a QEMU-only Linux-lock regression."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
# The PM lifetime audit applies to exactly these vendor sources.
SOURCE_SHA256 = {
    'uvm_global.c': '90b576b20b6110056c8970d9b611be3658763a22f9e80ee36212978bbc766b7e',
    'uvm_va_space.h': '27d792888f96f126e9c94d53d4b37eec8463cce78ae6710cbe9db40c2842aee2',
    'uvm_va_space.c': 'd3afb05ecd5a051312c5bad2f3406c01c9c75fda46a6323381551b96b1572dbf',
    'uvm.c': '81870dad066249991b39e2f1e70ddf0a48e4803eb48f487d0de7708c835a621a',
}


def function(text, name):
    match = re.search(r'^static NV_STATUS '+name+r'\(void\)\n\{', text, re.M)
    if not match:
        raise ValueError('Missing function '+name)
    start, pos, depth = match.start(), match.end(), 1
    # Restricted to the hash-pinned callbacks; their comments contain no braces.
    while depth:
        if text[pos] == '{':
            depth += 1
        if text[pos] == '}':
            depth -= 1
        pos += 1
    return text[start:pos]+'\n'


def macro(text, name):
    start = text.index('#define '+name+'(')
    return text[start:text.index('\n\n', start)]+'\n'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'kernel', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--legacy', action='store_true')
    args = parser.parse_args()
    if 'NVIDIA_VERSION = 615.78.08' not in (args.source/'version.mk').read_text():
        raise ValueError('Requires NVIDIA 615.78.08')
    source = args.source/'kernel-open/nvidia-uvm'
    for name, expected in SOURCE_SHA256.items():
        if sha(source/name) != expected:
            raise ValueError('Re-audit changed vendor source: '+name)
    out = args.output.resolve()
    out.mkdir()
    vendor = out/'vendor/kernel-open/nvidia-uvm'
    vendor.mkdir(parents=True)
    for name in ('uvm_global.c', 'uvm_va_space.h'):
        shutil.copy2(source/name, vendor/name)
    patch = ROOT/'platform/nvidia/nvidia-uvm-pm-lock-order.patch'
    if not args.legacy:
        subprocess.run(['patch', '-p1', '--fuzz=0', '--batch', '-i', str(patch)],
                       cwd=out/'vendor', check=True)
    code = (vendor/'uvm_global.c').read_text()
    header = (vendor/'uvm_va_space.h').read_text()
    inc = macro(header, 'uvm_va_space_down_write')+macro(header, 'uvm_va_space_up_write')
    if not args.legacy:
        inc += macro(header, 'uvm_va_space_down_write_pm')
    inc += function(code, 'uvm_suspend')+function(code, 'uvm_resume')
    (out/'callbacks.inc').write_text(inc)
    for name in ('Kbuild', 'n1x_uvm_pm_test.c'):
        shutil.copy2(HERE/name, out/name)
    buildfile = out/'Kbuild'
    buildfile.write_text(buildfile.read_text()+'ccflags-y += -DFIXED='+str(int(not args.legacy))+'\n')
    subprocess.run(['make', '-C', str(args.kernel.resolve()), 'M='+str(out),
                    'W=1', '-j2', 'modules'], check=True)
    manifest = {
        'fixed': not args.legacy,
        'source_inputs': {name: sha(source/name) for name in SOURCE_SHA256},
        'patch_sha256': sha(patch),
        'callbacks_sha256': sha(out/'callbacks.inc'),
        'module_sha256': sha(out/'n1x_uvm_pm_test.ko'),
        'installed': False,
        'host_modules_loaded': False,
    }
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    main()
