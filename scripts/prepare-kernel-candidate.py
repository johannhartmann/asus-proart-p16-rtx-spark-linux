#!/usr/bin/env python3
"""Stage and optionally build an isolated, signed-source P16 kernel candidate.

Does not install packages, modify boot files or change running modules.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEBUG_COMMON = {
    'DEBUG_KERNEL': 'y', 'PROVE_LOCKING': 'y', 'LOCKDEP': 'y',
    'DEBUG_LOCK_ALLOC': 'y', 'DEBUG_SPINLOCK': 'y', 'DEBUG_MUTEXES': 'y',
    'PROVE_RCU': 'y', 'DMA_API_DEBUG': 'y', 'KUNIT': 'y',
    'KUNIT_ALL_TESTS': 'n',
    # Container/Btrfs startup exhausts the default 16-bit chain budget before
    # DSP tests. Keep the validator active with four times as many chains and
    # held-lock entries. This changes debug capacity, not locking semantics.
    'LOCKDEP_CHAINS_BITS': '18',
}


def debug_settings(profile):
    if profile == 'none':
        return {}
    return dict(DEBUG_COMMON, KASAN='y' if profile == 'kasan' else 'n',
                KCSAN='y' if profile == 'kcsan' else 'n', **(
                    {'KASAN_GENERIC': 'y', 'KASAN_OUTLINE': 'y',
                     'KASAN_INLINE': 'n', 'KASAN_SW_TAGS': 'n', 'KASAN_HW_TAGS': 'n'}
                    if profile == 'kasan' else {'KCSAN_STRICT': 'y'}))


def set_config(raw, settings):
    text = raw.decode()
    for name, value in settings.items():
        pattern = r'^(?:CONFIG_' + name + r'=.*|# CONFIG_' + name + r' is not set)$'
        line = 'CONFIG_' + name + '=' + value if value != 'n' else '# CONFIG_' + name + ' is not set'
        text, count = re.subn(pattern, line, text, flags=re.M)
        if not count:
            text += '\n' + line + '\n'
    return text.encode()


def configure_debug_inputs(inputs, settings):
    if not settings:
        return
    original = inputs['kernel/config.aarch64']
    configured = set_config(original, settings)
    recipe = inputs['kernel/PKGBUILD'].decode()
    # Repin only our local config. Keep all upstream signatures/checksums.
    for algorithm, field in (('sha256', 'sha256sums_aarch64'),
                             ('blake2b', 'b2sums_aarch64')):
        old = hashlib.new(algorithm, original).hexdigest()
        new = hashlib.new(algorithm, configured).hexdigest()
        recipe, count = re.subn(r"^" + field + r"=\('" + old + r"'\)$",
                                field + "=('" + new + "')", recipe, flags=re.M)
        if count != 1:
            raise RuntimeError('Original config checksum does not match ' + field)
    inputs['kernel/config.aarch64'] = configured
    inputs['kernel/PKGBUILD'] = recipe.encode()


def verify_debug_config(path, settings):
    text = path.read_text()
    for name, value in settings.items():
        enabled = re.search(r'^CONFIG_' + name + r'=(.+)$', text, re.M)
        actual = enabled.group(1) if enabled else 'n'
        if actual != value:
            raise RuntimeError('Debug config was not retained by Kconfig: CONFIG_' + name)


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def process_start(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def verify_inputs(output, manifest):
    for name, digest in manifest['kernel_inputs'].items():
        path = output / name
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Staged kernel input changed: ' + name)


def package_recipe(raw, package_base):
    """Allow separately installed candidates without replacing the working kernel."""
    if not re.fullmatch(r'linux-p16-platform(?:-[1-9][0-9]*)?', package_base):
        raise RuntimeError('Invalid candidate package base')
    recipe, count = re.subn(r'^pkgbase=linux-p16-platform$',
                            'pkgbase=' + package_base, raw.decode(), flags=re.M)
    if count != 1:
        raise RuntimeError('Unexpected kernel package base')
    return recipe.encode()


def prepare(output, release, jobs, debug_profile='none', package_base='linux-p16-platform'):
    if output.exists():
        raise RuntimeError('Output already exists; use --resume only after a terminal build')
    names = subprocess.check_output(['git', 'ls-files', 'kernel'], cwd=ROOT, text=True).splitlines()
    inputs = {}
    for name in names:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Kernel input is not a regular file: ' + name)
        inputs[name] = path.read_bytes()
    settings = debug_settings(debug_profile)
    configure_debug_inputs(inputs, settings)
    inputs['kernel/PKGBUILD'] = package_recipe(inputs['kernel/PKGBUILD'], package_base)
    output.mkdir(parents=True, mode=0o700)
    for name, raw in inputs.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    manifest = {
        'created_at': now(),
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'local_kernel_inputs_pinned': True,
        'kernel_inputs': {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()},
        'pkgrel': release, 'jobs': jobs, 'package_base': package_base,
        'expected_release': f'7.2.8-{release}-rtx-spark-npu',
        'debug_profile': debug_profile, 'debug_config': settings,
        'source_date_epoch': subprocess.check_output(['git', 'show', '-s', '--format=%ct', 'HEAD'],
                                                      cwd=ROOT, text=True).strip(),
        'packages_installed': False, 'boot_files_written': False,
        'running_modules_changed': False, 'attempts': [],
    }
    save(output / 'manifest.json', manifest)
    return manifest


def record_packages(output, manifest, job):
    verify_inputs(output, manifest)
    actual = (output / 'kernel/src/linux-7.2.8/version').read_text().strip()
    generated = (output / 'kernel/src/linux-7.2.8/include/config/kernel.release').read_text().strip()
    if actual != manifest['expected_release'] or generated != actual:
        raise RuntimeError('Built release differs from the staged candidate: ' + actual)
    verify_debug_config(output / 'kernel/src/linux-7.2.8/.config', manifest.get('debug_config', {}))
    packages = sorted((output / 'packages').glob('*.pkg.tar.zst'))
    if len(packages) != 2:
        raise RuntimeError('Expected exactly a kernel and matching headers package')
    names = set()
    for path in packages:
        info = subprocess.check_output(['bsdtar', '-xOf', str(path), '.PKGINFO'], text=True)
        fields = dict(line.split(' = ', 1) for line in info.splitlines() if ' = ' in line)
        if fields.get('pkgver') != f"7.2.8-{manifest['pkgrel']}" or fields.get('arch') != 'aarch64':
            raise RuntimeError('Unexpected candidate package metadata: ' + path.name)
        names.add(fields.get('pkgname'))
    package_base = manifest.get('package_base', 'linux-p16-platform')
    if names != {package_base, package_base + '-headers'}:
        raise RuntimeError('Candidate package names do not match kernel and headers')
    manifest['packages'] = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in packages
    }
    if not any(item.get('log') == job['log'] for item in manifest['attempts']):
        manifest['attempts'].append(job)
    save(output / 'manifest.json', manifest)


def build(output, manifest):
    if os.geteuid() == 0:
        raise RuntimeError('Build as the normal workspace owner, not root')
    verify_inputs(output, manifest)
    job_path = output / 'job.json'
    if job_path.exists():
        previous = json.loads(job_path.read_text())
        if previous['status'] == 'complete':
            if previous.get('exit_code') != 0:
                raise RuntimeError('Inconsistent completed candidate job')
            record_packages(output, manifest, previous)
            print('Verified the completed candidate packages; no build restarted', flush=True)
            return
        if previous['status'] == 'running':
            started = process_start(previous['pid'])
            if started is not None and started == previous['process_start']:
                raise RuntimeError('The recorded makepkg process is still live; do not restart it')
    recipe = (output / 'kernel/PKGBUILD').read_text()
    match = re.search(r'^makedepends=\((.*?)\)', recipe, re.M | re.S)
    dependencies = shlex.split(match.group(1))
    check = subprocess.run(['pacman', '-T', *dependencies], capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError('Missing build dependencies; no packages installed: ' + check.stdout.strip())
    env = os.environ.copy()
    env.update({
        'GNUPGHOME': str(output / 'gnupg'),
        'PKGDEST': str(output / 'packages'),
        'SRCDEST': str(output / 'kernel'),
        'BUILDDIR': str(output / 'kernel'),
        'P16_KERNEL_RELEASE': str(manifest['pkgrel']),
        'MAKEFLAGS': '-j' + str(manifest['jobs']),
        'SOURCE_DATE_EPOCH': manifest['source_date_epoch'],
        'PKGEXT': '.pkg.tar.zst',
    })
    Path(env['GNUPGHOME']).mkdir(mode=0o700, exist_ok=True)
    Path(env['PKGDEST']).mkdir(exist_ok=True)
    keys = sorted((output / 'kernel/keys/pgp').glob('*.asc'))
    subprocess.run(['gpg', '--batch', '--import', *map(str, keys)], env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    attempt = len(manifest['attempts']) + 1
    log = output / f'build-{attempt}.log'
    command = ['makepkg', '--force', '--noconfirm']
    prepared = output / 'kernel/src/linux-7.2.8/version'
    if attempt > 1 and prepared.is_file() and prepared.read_text().strip() == manifest['expected_release']:
        command.append('--noextract')
    else:
        command.append('--cleanbuild')
    with log.open('w') as stream:
        process = subprocess.Popen(command, cwd=output / 'kernel', env=env,
                                   stdout=stream, stderr=subprocess.STDOUT)
        job = {'status': 'running', 'pid': process.pid, 'process_start': process_start(process.pid),
               'started_at': now(), 'command': command, 'log': str(log),
               'jobs': manifest['jobs'], 'pkgrel': manifest['pkgrel']}
        save(job_path, job)
        print(json.dumps(job), flush=True)
        code = process.wait()
    job.update({'status': 'complete' if code == 0 else 'failed',
                'exit_code': code, 'finished_at': now()})
    save(job_path, job)
    verify_inputs(output, manifest)
    if code == 0:
        record_packages(output, manifest, job)
    else:
        manifest['attempts'].append(job)
        save(output / 'manifest.json', manifest)
    print(json.dumps(job), flush=True)
    if code:
        raise RuntimeError('Kernel build failed; inspect ' + str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--release', type=int, default=28)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--package-base', default='linux-p16-platform',
                        help='use a numbered base to preserve an installed candidate')
    parser.add_argument('--debug', choices=('none', 'kasan', 'kcsan'), default='none',
                        help='separate debug candidate; preserves the installed kernel')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.release < 25 or args.jobs < 1:
        parser.error('Use a new release (25 or later) and a positive job limit')
    output = args.output.absolute()
    try:
        if args.resume:
            if not output.is_dir() or output.is_symlink():
                raise RuntimeError('Resume requires the original candidate directory')
            manifest = json.loads((output / 'manifest.json').read_text())
        else:
            manifest = prepare(output, args.release, args.jobs, args.debug, args.package_base)
        with (output / 'build.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            verify_inputs(output, manifest)
            if args.build:
                build(output, manifest)
        print(output / 'manifest.json')
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
