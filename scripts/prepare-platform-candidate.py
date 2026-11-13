#!/usr/bin/env python3
"""Build a matching P16 module set against an isolated candidate kernel.

Only files below --output are written. No modules are loaded or installed.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NPU = ROOT.parent / 'n1x-lab/npu'
FILES = {
    'dsp/validation': ('n1x_adsp_route_check.c', 'n1x_adsp_primary_check.c',
                       'n1x_adsp_task_check.c', 'Kbuild'),
    'dsp': ('n1x_adsp.c', 'n1x_adsp_client.h', 'n1x_adsp_pcm.h', 'n1x_adsp_ipc.h',
            'n1x_sroot_client.h', 'n1x_sroot_firmware.h', 'Kbuild',
            'n1x-adsp-audio.service', 'n1x-adsp-audio'),
    'pluton': ('n1x_pluton.c', 'n1x_pluton_protocol.h', 'n1x_pluton_uapi.h',
               'n1x_pcbi_protocol.h', 'Kbuild'),
    'scp': ('n1x_scp.c', 'Kbuild'),
    'als': ('hid-sensor-als.c', 'hid-sensor-trigger.h', 'Kbuild'),
    'tests': ('n1x-protocol-test.c', 'Kbuild'),
    'sensorhub': ('spi-hid-core.c', 'spi-hid-acpi.c', 'spi-hid.h', 'spi-hid-core.h',
                  'spi-hid-trace.h', 'Kbuild'),
}
MODULES = {'dsp': ('n1x_adsp.ko',),
           'dsp/validation': ('n1x_adsp_route_check.ko', 'n1x_adsp_primary_check.ko',
                              'n1x_adsp_task_check.ko'), 'provider': ('n1x_npu_bootstrap.ko',),
           'pluton': ('n1x_pluton.ko',), 'scp': ('n1x_scp.ko',),
           'als': ('hid-sensor-als.ko',), 'sensorhub': ('spi-hid.ko', 'spi-hid-acpi.ko'),
           'hwmon': ('spbm.ko',),
           'nvidia': ('nvidia.ko', 'nvidia-drm.ko', 'nvidia-modeset.ko',
                      'nvidia-uvm.ko', 'nvidia-peermem.ko')}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def process_start(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def copy_input(source, target, recorded, output):
    if source.is_symlink() or not source.is_file():
        raise RuntimeError('Expected a regular module source: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = source.read_bytes()
    target.write_bytes(raw)
    target.chmod(source.stat().st_mode & 0o777)
    recorded[str(target.relative_to(output))] = hashlib.sha256(raw).hexdigest()


def stage(args):
    parent = args.kernel_candidate.resolve(strict=True)
    kernel_manifest = json.loads((parent / 'manifest.json').read_text())
    release = kernel_manifest['expected_release']
    kernel = parent / 'kernel/src/linux-7.2.8'
    if (kernel / 'version').read_text().strip() != release:
        raise RuntimeError('The candidate kernel has not completed preparation')
    output = args.output.absolute()
    if output.exists():
        raise RuntimeError('Module output already exists')
    output.mkdir(parents=True, mode=0o700)
    inputs = {}
    for kind, names in FILES.items():
        for name in names:
            copy_input(ROOT / 'platform' / kind / name, output / kind / name, inputs, output)
    copy_input(ROOT / 'platform/dsp/afe/mt8901-afe-sram.h',
               output / 'dsp/mt8901-afe-sram.h', inputs, output)
    receipt = json.loads((ROOT / 'platform/dsp/provider/receipt.json').read_text())
    for name, expected in receipt['snapshot']['files'].items():
        source = NPU / name
        if digest(source) != expected:
            raise RuntimeError('Provider source differs from its package snapshot: ' + name)
        copy_input(source, output / 'provider' / name, inputs, output)
    hwmon = args.hwmon_source.resolve(strict=True)
    hwmon_patch = ROOT / 'platform/hwmon/n1x-platform.patch'
    actual_patch = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=hwmon)
    if actual_patch != hwmon_patch.read_bytes():
        raise RuntimeError('The hwmon source differs from its maintained platform patch')
    if subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=hwmon).strip():
        raise RuntimeError('The hwmon source contains untracked files')
    hwmon_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=hwmon, text=True).strip()
    for name in ('spbm.c', 'n1x-mmio.h', 'n1x-acpi.h'):
        copy_input(hwmon / name, output / 'hwmon' / name, inputs, output)
    (output / 'hwmon/Kbuild').write_text('obj-m += spbm.o\n')
    inputs['hwmon/Kbuild'] = digest(output / 'hwmon/Kbuild')
    nvidia = args.nvidia_source.resolve(strict=True)
    version = re.search(r'^NVIDIA_VERSION\s*=\s*(\S+)', (nvidia / 'version.mk').read_text(), re.M)
    loaded_version = Path('/sys/module/nvidia/version').read_text().strip()
    if not version or version.group(1) != loaded_version:
        raise RuntimeError('NVIDIA source version differs from the running driver')
    for directory, dirs, names in os.walk(nvidia):
        dirs[:] = [name for name in dirs if name not in ('.git', '_out')]
        for name in sorted(names):
            if name in ('Module.symvers', 'modules.order') or name.endswith(('.o', '.ko', '.cmd', '.mod', '.mod.c')):
                continue
            source = Path(directory) / name
            copy_input(source, output / 'nvidia' / source.relative_to(nvidia), inputs, output)
    manifest = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'kernel_candidate': str(parent), 'kernel_tree': str(kernel),
        'kernel_release': release,
        'source_boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'loader_abi': 4, 'playback_abi': 3, 'jobs': args.jobs, 'inputs': inputs,
        'hwmon_source_commit': hwmon_head, 'hwmon_patch_sha256': digest(hwmon_patch),
        'nvidia_version': loaded_version,
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'npu_source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=NPU, text=True).strip(),
        'installed': False, 'modules_loaded': False, 'boot_files_written': False,
        'hardware_qualified': False, 'builds': {},
    }
    save(output / 'manifest.json', manifest)
    return output, manifest


def verify_sources(output, manifest):
    for name, expected in manifest['inputs'].items():
        path = output / name
        if path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise RuntimeError('Module input changed: ' + name)


def modinfo(field, path):
    return subprocess.check_output(['modinfo', '-F', field, str(path)], text=True).strip()


def build(output, manifest):
    if os.geteuid() == 0:
        raise RuntimeError('Build as the normal workspace owner')
    job_path = output / 'job.json'
    if job_path.exists():
        previous = json.loads(job_path.read_text())
        if previous.get('status') == 'running':
            started = process_start(previous['pid'])
            if started is not None and started == previous.get('process_start'):
                raise RuntimeError('The recorded module build is still live; do not restart it')
    parent = Path(manifest['kernel_candidate'])
    job = json.loads((parent / 'job.json').read_text())
    if job.get('status') != 'complete' or job.get('exit_code') != 0:
        raise RuntimeError('Wait for the live kernel build; it must complete before module builds')
    kernel_manifest = json.loads((parent / 'manifest.json').read_text())
    for name, expected in kernel_manifest['packages'].items():
        if digest(parent / name) != expected:
            raise RuntimeError('Candidate kernel package changed: ' + name)
    verify_sources(output, manifest)
    kernel = Path(manifest['kernel_tree'])
    release = manifest['kernel_release']
    module_set = dict(MODULES)
    if kernel_manifest.get('debug_profile', 'none') != 'none':
        module_set['tests'] = ('n1x-protocol-test.ko',)
    for kind, modules in module_set.items():
        if kind in manifest['builds']:
            for name, artifact in manifest['builds'][kind]['modules'].items():
                path = Path(artifact['path'])
                if path.is_symlink() or not path.is_file() or digest(path) != artifact['sha256']:
                    raise RuntimeError('Completed module output changed: ' + name)
                if modinfo('vermagic', path).split()[0] != release:
                    raise RuntimeError('Completed module vermagic differs from candidate kernel: ' + name)
            continue
        directory = output / kind
        if kind == 'provider':
            directory /= 'driver'
        log = output / (kind + '-build.log')
        if kind == 'nvidia':
            command = ['make', '-C', str(directory), '-j' + str(manifest['jobs']),
                       'SYSSRC=' + str(kernel), 'SYSOUT=' + str(kernel),
                       'KERNEL_UNAME=' + release, 'IGNORE_PREEMPT_RT_PRESENCE=1',
                       'NV_EXCLUDE_BUILD_MODULES=', 'modules']
        else:
            command = ['make', '-C', str(kernel), 'M=' + str(directory), 'W=1',
                       '-j' + str(manifest['jobs']), 'modules']
            if kind == 'dsp/validation':
                command.append('KBUILD_EXTRA_SYMBOLS=' + str(output / 'dsp/Module.symvers'))
            if kind == 'tests':
                command.append('CONFIG_N1X_PROTOCOL_KUNIT_TEST=m')
        with log.open('w') as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
            save(job_path, {'status': 'running', 'component': kind, 'pid': process.pid,
                                      'process_start': process_start(process.pid),
                                      'command': command, 'log': str(log)})
            code = process.wait()
        result = {'exit_code': code, 'command': command, 'log': str(log), 'modules': {}}
        save(job_path, {'status': 'complete' if code == 0 else 'failed',
                                  'component': kind, 'exit_code': code, 'log': str(log)})
        if code:
            raise RuntimeError('Module build failed: ' + str(log))
        for name in modules:
            paths = list(directory.rglob(name))
            if len(paths) != 1:
                raise RuntimeError('Expected one module output: ' + name)
            path = paths[0]
            if modinfo('vermagic', path).split()[0] != release:
                raise RuntimeError('Module vermagic differs from candidate kernel: ' + name)
            result['modules'][name] = {'path': str(path), 'sha256': digest(path),
                                       'srcversion': modinfo('srcversion', path),
                                       'version': modinfo('version', path)}
        manifest['builds'][kind] = result
        save(output / 'manifest.json', manifest)
        print(kind + ': candidate module build complete', flush=True)
    verify_sources(output, manifest)
    afe = kernel / 'sound/soc/mediatek/mt8901/snd-soc-mt8901-afe.ko'
    if modinfo('vermagic', afe).split()[0] != release:
        raise RuntimeError('AFE vermagic differs from candidate kernel')
    symbols = (kernel / 'Module.symvers').read_text()
    for name in ('mt8901_afe_sram_retire', 'mt8901_afe_sram_stop_irq',
                 'mt8901_afe_sram_prepare_irq', 'mt8901_afe_sram_rebind',
                 'mt8901_afe_sram_allow_retention', 'mt8901_afe_sram_suspend',
                 'mt8901_afe_sram_resume'):
        if '\t' + name + '\t' not in symbols:
            raise RuntimeError('Candidate kernel lacks AFE helper: ' + name)
    machine = kernel / 'sound/soc/mediatek/mt8901/mt8901-acp-sdw-legacy-mach.ko'
    if modinfo('vermagic', machine).split()[0] != release:
        raise RuntimeError('ASoC machine vermagic differs from candidate kernel')
    manifest['drivers'] = {
        'dsp': manifest['builds']['dsp']['modules']['n1x_adsp.ko'],
        'provider': manifest['builds']['provider']['modules']['n1x_npu_bootstrap.ko'],
        'afe': {'path': str(afe), 'sha256': digest(afe), 'srcversion': modinfo('srcversion', afe)},
        'machine': {'path': str(machine), 'sha256': digest(machine),
                    'srcversion': modinfo('srcversion', machine)},
    }
    # A kernel relink can renumber base BTF types without changing vermagic or
    # symbol CRCs. Validate both in-tree and external module BTF before staging.
    artifacts = [item['path'] for build_result in manifest['builds'].values()
                 for item in build_result['modules'].values()]
    subprocess.run(['python3', str(ROOT / 'scripts/verify-module-btf.py'),
                    '--vmlinux', str(kernel / 'vmlinux'),
                    '--kernel-image', str(kernel / 'arch/arm64/boot/Image'),
                    '--module-dir', str(kernel), *artifacts], check=True)
    manifest['source_hashes_still_match'] = True
    save(output / 'manifest.json', manifest)
    print(output / 'manifest.json', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--nvidia-source', type=Path)
    parser.add_argument('--hwmon-source', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--sources-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    try:
        if args.resume:
            if args.output.is_symlink() or not args.output.is_dir():
                raise RuntimeError('Resume requires the original module candidate directory')
            output = args.output.resolve(strict=True)
            manifest = json.loads((output / 'manifest.json').read_text())
        else:
            if not args.kernel_candidate or not args.nvidia_source or not args.hwmon_source or args.jobs < 1:
                parser.error('Provide kernel candidate, NVIDIA/hwmon source directories and positive jobs')
            output, manifest = stage(args)
        with (output / 'build.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            verify_sources(output, manifest)
            if not args.sources_only:
                build(output, manifest)
            else:
                print(output / 'manifest.json')
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
