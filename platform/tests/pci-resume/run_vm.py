#!/usr/bin/env python3
"""QEMU-only suspended-SDHCI hot-removal test. Never installs a host module."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True, help='Exact built guest kernel tree')
    parser.add_argument('--firmware', type=Path, required=True, help='Directory with AAVMF_CODE.no-secboot.fd and AAVMF_VARS.fd')
    parser.add_argument('--output', type=Path, required=True, help='New result directory')
    parser.add_argument('--expect-legacy', action='store_true')
    args = parser.parse_args()
    kernel, firmware, out = (p.resolve() for p in (args.kernel, args.firmware, args.output))
    if os.geteuid() == 0:
        parser.error('Run as the normal workspace user; root is not needed')
    out.mkdir(parents=True, exist_ok=False)
    os.sched_setaffinity(0, {0, 1, 10, 11})
    for name in ('Kbuild', 'n1x_sdhci_remove_test.c'):
        shutil.copy2(HERE/name, out/name)
    build = ['make', '-C', str(kernel), 'M='+str(out), 'W=1', '-j2']
    # A targeted M=drivers/mmc/host build emits its own current export CRCs.
    # Use that standard dependency dump; never force or disable modversions.
    extra_symbols = kernel/'drivers/mmc/host/Module.symvers'
    if extra_symbols.is_file():
        build.append('KBUILD_EXTRA_SYMBOLS='+str(extra_symbols))
    subprocess.run(build+['modules'], check=True)
    subprocess.run(['cc', '-static', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-DEXPECT_LEGACY='+str(int(args.expect_legacy)), str(HERE/'init.c'),
                    '-o', str(out/'init')], check=True)
    listing = 'dir /dev 0755 0 0\nnod /dev/console 0600 0 0 c 5 1\ndir /sys 0755 0 0\ndir /proc 0755 0 0\n'
    listing += f'file /init {out}/init 0755 0 0\nfile /model.ko {out}/n1x_sdhci_remove_test.ko 0644 0 0\n'
    for name in ('cqhci', 'sdhci', 'sdhci-uhs2', 'sdhci-pci'):
        module = kernel/'drivers/mmc/host'/(name+'.ko')
        if not module.is_file():
            raise RuntimeError('Missing matching SDHCI dependency: '+str(module))
        listing += f'file /{name}.ko {module} 0644 0 0\n'
    (out/'init.list').write_text(listing)
    with (out/'init.cpio').open('wb') as stream:
        subprocess.run([str(kernel/'usr/gen_init_cpio'), str(out/'init.list')], stdout=stream, check=True)
    (out/'cmdline').write_text('console=ttyAMA0 earlycon=efifb keep_bootcon pcie_ports=native loglevel=7 panic=0\n')
    (out/'osrel').write_text('ID=n1x-test\nNAME=Isolated PCI resume regression\n')
    (out/'esp/EFI/BOOT').mkdir(parents=True)
    # Use mkinitcpio's own EFI section alignment, as for the existing boot qualification.
    source = Path('/usr/bin/mkinitcpio').read_text()
    functions = source.split('want_file() {', 1)[1].split('\nbuild_uki() {', 1)[0]
    (out/'uki-functions').write_text('want_file() {'+functions)
    release = (kernel/'include/config/kernel.release').read_text().strip()
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
    subprocess.run(['bash', '-c', script, 'vm-uki', str(out), str(kernel), release], check=True)
    shutil.copy2(firmware/'AAVMF_VARS.fd', out/'vars.fd')
    qmp_path = out/'qmp.sock'
    command = ['qemu-system-aarch64', '-machine', 'virt,accel=kvm,gic-version=3',
               '-cpu', 'host', '-m', '4096', '-smp', '1',
               '-drive', 'if=pflash,format=raw,readonly=on,file='+str(firmware/'AAVMF_CODE.no-secboot.fd'),
               '-drive', 'if=pflash,format=raw,file='+str(out/'vars.fd'),
               '-drive', 'if=none,id=esp,format=raw,readonly=on,file=fat:ro:'+str(out/'esp'),
               '-device', 'virtio-blk-pci,drive=esp', '-device', 'virtio-rng-pci',
               '-device', 'pcie-root-port,id=hp,slot=1,chassis=1,addr=0x5',
               '-device', 'pcie-pci-bridge,id=sdbridge,bus=hp',
               '-device', 'sdhci-pci,id=sdtest,bus=sdbridge,addr=0x1', '-device', 'ramfb',
               '-display', 'none', '-nodefaults', '-serial', 'file:'+str(out/'uart.log'),
               '-monitor', 'none', '-qmp', 'unix:'+str(qmp_path)+',server=on,wait=off',
               '-nic', 'none', '-no-reboot']
    boot = Path('/proc/sys/kernel/random/boot_id').read_text()
    profile = Path('/sys/firmware/acpi/platform_profile').read_text()
    process = None
    connection = None
    started = time.monotonic()
    requested = False
    result = {'passed': False, 'kernel': release, 'legacy_positive_control': args.expect_legacy,
              'image_sha256': hashlib.sha256((kernel/'arch/arm64/boot/Image').read_bytes()).hexdigest(),
              'host_pm_requested': False, 'host_modules_loaded': False}
    try:
        with (out/'stderr.log').open('w') as errors:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors)
            while process.poll() is None:
                log = (out/'uart.log').read_text(errors='replace') if (out/'uart.log').exists() else ''
                assert time.monotonic()-started < 120, log[-3000:]
                assert boot == Path('/proc/sys/kernel/random/boot_id').read_text()
                assert profile == Path('/sys/firmware/acpi/platform_profile').read_text()
                temperatures = [int(p.read_text()) for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')]
                assert not temperatures or max(temperatures)<90000, 'Host thermal limit; stop own VM'
                if 'SDHCI_VM_READY_FOR_HOTREMOVE' in log and not requested:
                    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    connection.settimeout(3)
                    connection.connect(str(qmp_path))
                    qmp = connection.makefile('rwb', buffering=0)
                    json.loads(qmp.readline())
                    qmp.write(b'{"execute":"qmp_capabilities"}\n')
                    while 'return' not in json.loads(qmp.readline()):
                        pass
                    qmp.write(b'{"execute":"device_del","arguments":{"id":"sdbridge"}}\n')
                    requested = True
                if 'Kernel panic' in log:
                    raise RuntimeError('Guest test failed: '+log[-3500:])
                time.sleep(.2)
        log = (out/'uart.log').read_text(errors='replace')
        assert process.returncode==0 and 'SDHCI_VM_PASS' in log, (out/'stderr.log').read_text()+log[-3500:]
        result.update(passed=True, seconds=time.monotonic()-started, hot_remove_requested=requested)
        print(json.dumps(result, indent=2), flush=True)
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        if connection:
            connection.close()
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
