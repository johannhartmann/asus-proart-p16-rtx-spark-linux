#!/usr/bin/env python3
"""Exercise MMU notifier insertion with Lockdep in an isolated AArch64 EFI/KVM guest."""

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
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel', 'firmware', 'module', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--pre-register', action='store_true')
    parser.add_argument('--expect-warning', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run unprivileged; this test must not load a host module')
    if args.expect_warning and not args.pre_register:
        parser.error('The warning control requires pre-registration')

    kernel, firmware, module, output = (
        p.resolve() for p in (args.kernel, args.firmware, args.module, args.output)
    )
    release = (kernel / 'include/config/kernel.release').read_text().strip()
    config = (kernel / '.config').read_text()
    if 'CONFIG_PROVE_LOCKING=y' not in config or 'CONFIG_MMU_NOTIFIER=y' not in config:
        parser.error('Kernel requires PROVE_LOCKING and MMU_NOTIFIER')
    output.mkdir(parents=True, exist_ok=False)
    image = kernel / 'arch/arm64/boot/Image'
    if not image.is_file() or not module.is_file():
        parser.error('Kernel Image or module missing')
    if subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).split()[0] != release:
        parser.error('Module vermagic does not match kernel release')

    params = 'pre_register=' + str(int(args.pre_register))
    subprocess.run(['cc', '-static', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-DMODEL_PARAMETERS="' + params + '"', str(HERE / 'init.c'),
                    '-o', str(output / 'init')], check=True)
    listing = ('dir /dev 0755 0 0\nnod /dev/console 0600 0 0 c 5 1\n'
               'dir /sys 0755 0 0\ndir /proc 0755 0 0\n'
               f'file /init {output}/init 0755 0 0\n'
               f'file /model.ko {module} 0644 0 0\n')
    (output / 'init.list').write_text(listing)
    with (output / 'init.cpio').open('wb') as stream:
        subprocess.run([str(kernel / 'usr/gen_init_cpio'), str(output / 'init.list')],
                       stdout=stream, check=True)
    (output / 'cmdline').write_text('console=ttyAMA0 earlycon=efifb loglevel=7 panic=0\n')
    (output / 'osrel').write_text('ID=n1x-mmu-notifier-test\nNAME=N1X MMU notifier Lockdep test\n')
    (output / 'esp/EFI/BOOT').mkdir(parents=True)
    mkinitcpio = Path('/usr/bin/mkinitcpio').read_text()
    functions = mkinitcpio.split('want_file() {', 1)[1].split('\nbuild_uki() {', 1)[0]
    (output / 'uki-functions').write_text('want_file() {' + functions)
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
    subprocess.run(['bash', '-c', script, 'mmu-test', str(output), str(kernel), release], check=True)
    shutil.copy2(firmware / 'AAVMF_VARS.fd', output / 'vars.fd')

    command = ['qemu-system-aarch64', '-machine', 'virt,accel=kvm,gic-version=3',
               '-cpu', 'host', '-m', '4096', '-smp', '1',
               '-drive', 'if=pflash,format=raw,readonly=on,file=' + str(firmware / 'AAVMF_CODE.no-secboot.fd'),
               '-drive', 'if=pflash,format=raw,file=' + str(output / 'vars.fd'),
               '-drive', 'if=none,id=esp,format=raw,readonly=on,file=fat:ro:' + str(output / 'esp'),
               '-device', 'virtio-blk-pci,drive=esp', '-device', 'virtio-rng-pci',
               '-device', 'ramfb', '-display', 'none', '-nodefaults',
               '-serial', 'file:' + str(output / 'uart.log'),
               '-monitor', 'none', '-nic', 'none', '-no-reboot']
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text()
    profile_path = Path('/sys/firmware/acpi/platform_profile')
    profile = profile_path.read_text() if profile_path.exists() else None
    result = {'passed': False, 'kernel': release, 'pre_register': args.pre_register,
              'expected_warning': args.expect_warning,
              'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
              'module_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
              'host_modules_loaded': False, 'host_pm_requested': False}
    process = None
    start = time.monotonic()
    try:
        with (output / 'stderr.log').open('w') as stderr:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr)
            while process.poll() is None:
                if time.monotonic() - start > 120:
                    raise RuntimeError('Guest timeout')
                if boot_id != Path('/proc/sys/kernel/random/boot_id').read_text():
                    raise RuntimeError('Host rebooted during guest test')
                if profile is not None and profile != profile_path.read_text():
                    raise RuntimeError('Host power profile changed')
                temperatures = [int(path.read_text()) for path in
                                Path('/sys/class/thermal').glob('thermal_zone*/temp')]
                if temperatures and max(temperatures) >= 90000:
                    raise RuntimeError('Host thermal stop')
                time.sleep(.2)
        log = (output / 'uart.log').read_text(errors='replace')
        if process.returncode != 0 or 'N1X_MMU_NOTIFIER_INIT_RESULT result=0' not in log:
            raise RuntimeError('Guest/module failed: ' + log[-4000:])
        marker = (f'N1X_MMU_NOTIFIER_TEST_PASS pre_register={int(args.pre_register)} '
                  f'debug_locks={int(not args.expect_warning)}')
        if marker not in log:
            raise RuntimeError('Model marker missing: ' + log[-4000:])
        warnings = re.findall(r'WARNING:', log)
        if len(warnings) != int(args.expect_warning):
            raise RuntimeError('Unexpected warning count: ' + log[-5000:])
        if args.expect_warning and 'possible recursive locking detected' not in log:
            raise RuntimeError('Expected mmap_lock recursion marker missing')
        if re.search(r'Kernel panic|BUG:|Oops:|KASAN:', log):
            raise RuntimeError('Guest kernel fault: ' + log[-5000:])
        result.update(passed=True, warning_count=len(warnings), seconds=time.monotonic() - start)
        print(json.dumps(result, indent=2))
    except BaseException as error:
        result['error'] = str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
