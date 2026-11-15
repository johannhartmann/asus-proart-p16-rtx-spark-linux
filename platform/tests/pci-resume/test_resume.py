#!/usr/bin/env python3
"""Offline regressions using functions extracted from the pinned kernel and patches."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PATCHES = ('pciehp-defer-system-resume.patch', 'sdhci-irq-ownership.patch',
           'pciehp-reset-lock-order.patch')


def function(code, name):
    match = re.search(r'^(?:static\s+)?(?:int|void|bool)\s+' + re.escape(name) + r'\([^;]*?\)\s*\{', code, re.M)
    if not match:
        raise ValueError('Missing production function ' + name)
    # Lexically blank comments and literals for brace counting.
    clean = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                   lambda m: ' ' * len(m[0]), code, flags=re.S)
    opening = code.index('{', match.start())
    depth = 0
    for index in range(opening, len(clean)):
        depth += (clean[index] == '{') - (clean[index] == '}')
        if not depth:
            return code[match.start():index + 1] + '\n'
    raise ValueError('Unterminated production function ' + name)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Prepared Linux 7.2.8 predecessor source, before the three resume patches')
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    files = {'drivers/pci/hotplug/pciehp_ctrl.c'}
    for name in PATCHES:
        files.update(re.findall(r'^--- a/(.+)$', (ROOT/'kernel'/name).read_text(), re.M))
    for kind in ('legacy', 'fixed'):
        for name in files:
            target = out/kind/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source/name, target)
    for name in PATCHES:
        subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i', str(ROOT/'kernel'/name)],
                       cwd=out/'fixed', check=True)
    manifest = {'patches': {p: digest(ROOT/'kernel'/p) for p in PATCHES},
                'source': {p: digest(source/p) for p in sorted(files)}, 'cases': []}
    for kind in ('legacy', 'fixed'):
        tree = out/kind
        sdhci = (tree/'drivers/mmc/host/sdhci.c').read_text()
        names = ([] if kind == 'legacy' else ['sdhci_free_irq']) + [
            'sdhci_suspend_host', 'sdhci_resume_host', '__sdhci_add_host', 'sdhci_remove_host']
        (tree/'sdhci.inc').write_text('\n'.join(function(sdhci, n) for n in names))
        hotplug = (tree/'drivers/pci/hotplug/pciehp_core.c').read_text()
        names = ['pciehp_resume_noirq', 'pciehp_resume'] + ([] if kind == 'legacy' else [
            'pciehp_system_resume']) + ['pciehp_runtime_suspend', 'pciehp_runtime_resume']
        (tree/'hotplug.inc').write_text('\n'.join(function(hotplug, n) for n in names))
        request = (tree/'drivers/pci/hotplug/pciehp_ctrl.c').read_text()
        (tree/'request.inc').write_text(function(request, 'pciehp_request'))
        pci = (tree/'drivers/pci/pci.c').read_text()
        hotplug_pci = (tree/'drivers/pci/hotplug/pciehp_pci.c').read_text()
        names = ['pci_reset_bridge'] + ([] if kind == 'legacy' else ['pci_reset_bus_unlocked']) + ['pci_reset_bus']
        (tree/'locking.inc').write_text('\n'.join(function(hotplug_pci, n) for n in (
            'pciehp_configure_device', 'pciehp_unconfigure_device')) + '\n' +
            '\n'.join(function(pci, n) for n in names))
        for fixture in ('sdhci', 'hotplug', 'locking'):
            binary = tree/fixture
            subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-parameter', '-Wno-unused-function',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
                            '-DLEGACY=' + str(int(kind == 'legacy')), '-I' + str(tree),
                            str(HERE/(fixture+'-fixture.c')), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=20)
            manifest['cases'].append({'variant': kind, 'fixture': fixture,
                                      'binary_sha256': digest(binary), 'passed': True})
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(out/'manifest.json')


if __name__ == '__main__':
    main()
