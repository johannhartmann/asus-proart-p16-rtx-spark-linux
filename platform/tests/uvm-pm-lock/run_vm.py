#!/usr/bin/env python3
"""Run one extracted UVM PM case in a bounded, unprivileged EFI/KVM guest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel', 'firmware', 'module', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--legacy', action='store_true')
    p.add_argument('--positive', action='store_true')
    p.add_argument('--va-spaces', type=int, choices=(0, 1, 2, 8), required=True)
    p.add_argument('--cpus', type=int, nargs='+')
    a = p.parse_args()
    if os.geteuid() == 0:
        p.error('Run unprivileged; no host modules or PM are involved')
    if a.positive and (a.legacy or not a.va_spaces):
        p.error('Positive control requires fixed callbacks and at least one VA')
    kernel, fw, module, out = (x.resolve() for x in (a.kernel, a.firmware, a.module, a.output))
    if a.cpus:
        if not set(a.cpus).issubset(os.sched_getaffinity(0)):
            p.error('CPU affinity unavailable')
        os.sched_setaffinity(0, set(a.cpus))
    out.mkdir(parents=True, exist_ok=False)
    params = f'run_test=1 va_spaces={a.va_spaces} positive={int(a.positive)}'
    subprocess.run(['cc', '-static', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-DMODEL_PARAMETERS="'+params+'"', str(HERE/'init.c'), '-o', str(out/'init')], check=True)
    listing = 'dir /dev 0755 0 0\nnod /dev/console 0600 0 0 c 5 1\ndir /sys 0755 0 0\ndir /proc 0755 0 0\n'
    listing += f'file /init {out}/init 0755 0 0\nfile /model.ko {module} 0644 0 0\n'
    (out/'init.list').write_text(listing)
    with (out/'init.cpio').open('wb') as f:
        subprocess.run([str(kernel/'usr/gen_init_cpio'), str(out/'init.list')], stdout=f, check=True)
    (out/'cmdline').write_text('console=ttyAMA0 earlycon=efifb loglevel=7 panic=0\n')
    (out/'osrel').write_text('ID=uvm-pm-test\nNAME=Isolated UVM PM lock regression\n')
    (out/'esp/EFI/BOOT').mkdir(parents=True)
    source = Path('/usr/bin/mkinitcpio').read_text()
    functions = source.split('want_file() {', 1)[1].split('\nbuild_uki() {', 1)[0]
    (out/'uki-functions').write_text('want_file() {'+functions)
    script = '''set -euo pipefail
source /usr/lib/initcpio/functions
quiet(){ :; };warning(){ :; };_optnoukify=1;_optquiet=1;_tmpfiles=()
KERNELVERSION="$3"
source "$1/uki-functions"
uki_init /usr/lib/systemd/boot/efi/linuxaa64.efi.stub ""
uki_add_section .cmdline "$1/cmdline"
uki_add_section .osrel "$1/osrel"
uki_add_section .linux "$2/arch/arm64/boot/Image"
uki_add_section .initrd "$1/init.cpio"
uki_assemble "$1/esp/EFI/BOOT/BOOTAA64.EFI"
'''
    release = (kernel/'include/config/kernel.release').read_text().strip()
    subprocess.run(['bash', '-c', script, 'uvm-test', str(out), str(kernel), release], check=True)
    shutil.copy2(fw/'AAVMF_VARS.fd', out/'vars.fd')
    command = ['qemu-system-aarch64', '-machine', 'virt,accel=kvm,gic-version=3',
               '-cpu', 'host', '-m', '4096', '-smp', '1',
               '-drive', 'if=pflash,format=raw,readonly=on,file='+str(fw/'AAVMF_CODE.no-secboot.fd'),
               '-drive', 'if=pflash,format=raw,file='+str(out/'vars.fd'),
               '-drive', 'if=none,id=esp,format=raw,readonly=on,file=fat:ro:'+str(out/'esp'),
               '-device', 'virtio-blk-pci,drive=esp', '-device', 'virtio-rng-pci', '-device', 'ramfb',
               '-display', 'none', '-nodefaults', '-serial', 'file:'+str(out/'uart.log'),
               '-monitor', 'none', '-nic', 'none', '-no-reboot']
    boot = Path('/proc/sys/kernel/random/boot_id').read_text()
    profile_path = Path('/sys/firmware/acpi/platform_profile')
    profile = profile_path.read_text() if profile_path.exists() else None
    result = dict(passed=False, kernel=release, legacy=a.legacy, positive=a.positive,
                  va_spaces=a.va_spaces, host_pm_requested=False, host_modules_loaded=False,
                  image_sha256=hashlib.sha256((kernel/'arch/arm64/boot/Image').read_bytes()).hexdigest(),
                  module_sha256=hashlib.sha256(module.read_bytes()).hexdigest())
    process = None
    start = time.monotonic()
    try:
        with (out/'stderr.log').open('w') as f:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=f)
            while process.poll() is None:
                if time.monotonic()-start > 120: raise RuntimeError('Guest timeout')
                assert boot == Path('/proc/sys/kernel/random/boot_id').read_text()
                if profile is not None: assert profile == profile_path.read_text()
                temps = [int(t.read_text()) for t in Path('/sys/class/thermal').glob('thermal_zone*/temp')]
                if temps and max(temps) >= 90000: raise RuntimeError('Host thermal stop')
                time.sleep(.2)
        log = (out/'uart.log').read_text(errors='replace')
        assert process.returncode == 0 and 'UVM_PM_INIT_RESULT result=0' in log, log[-6000:]
        assert 'UVM_PM_LOCK_TEST_PASS' in log, log[-6000:]
        assert not re.search(r'Kernel panic|BUG:|Oops:|KASAN:', log), log[-6000:]
        expected_warning = (a.legacy and a.va_spaces > 0) or a.positive
        warnings = re.findall(r'WARNING:', log)
        assert len(warnings) == int(expected_warning), log[-6000:]
        if expected_warning:
            assert ('possible circular locking dependency' in log or 'possible recursive locking' in log), log[-6000:]
        line = next(x for x in log.splitlines() if 'UVM_PM_LOCK_RESULT ' in x)
        fields = dict(re.findall(r'(\w+)=(\d+)', line.split('UVM_PM_LOCK_RESULT ', 1)[1]))
        assert fields == dict(fixed=str(int(not a.legacy)), va_spaces=str(a.va_spaces),
                              positive=str(int(a.positive)), cycles='1' if a.legacy else '4',
                              mutations='1' if a.legacy else '4', debug_locks=str(int(not expected_warning)),
                              expected=str(int(not expected_warning)), failures='0'), fields
        result.update(passed=True, seconds=time.monotonic()-start, checks=fields)
        print(json.dumps(result, indent=2))
    except BaseException as error:
        result['error'] = str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')

if __name__ == '__main__':
    main()
