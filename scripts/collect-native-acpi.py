#!/usr/bin/env python3
"""Record a boot's ACPI/power evidence without changing controls or suspending."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import pwd
import subprocess

SPEC = importlib.util.spec_from_file_location('acpi_compare_stage', Path(__file__).with_name('stage-native-acpi.py'))
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)
NATIVE_SSDT = '46d9ed16af06093cdb849df69646683317d53d7342dfd38f24eab00795d396f0'


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError as error:
        return {'error': str(error)}


def power_state():
    files = [Path('/sys/firmware/acpi/platform_profile'),
             Path('/sys/firmware/acpi/platform_profile_choices'), Path('/sys/power/mem_sleep')]
    for device in Path('/sys/class/power_supply').glob('*'):
        files.extend(device / name for name in ('type', 'online', 'status', 'capacity',
                     'energy_now', 'charge_now', 'voltage_now', 'current_now', 'power_now',
                     'charge_control_end_threshold') if (device / name).exists())
    for device in Path('/sys/class/hwmon').glob('*'):
        files.extend(device.glob('name'))
        for pattern in ('temp*_input', 'fan*_input', 'power*_input', 'power*_average'):
            files.extend(device.glob(pattern))
    return {str(path): read(path) for path in sorted(set(files))}


def collect(candidate_dir, phase, output):
    candidate_dir, output = Path(candidate_dir), Path(output)
    manifest = json.loads((candidate_dir / 'manifest.json').read_text())
    candidate = candidate_dir / 'native-acpi.efi'
    if STAGE.digest(candidate.read_bytes()) != manifest['candidate_sha256']:
        raise ValueError('Candidate differs from its staging manifest')
    expected_command = STAGE.BOOT.sections(candidate)['.cmdline'].rstrip(b'\0\n ').decode()
    command = Path('/proc/cmdline').read_text().strip()
    tables = {}
    for path in sorted(Path('/sys/firmware/acpi/tables').glob('*')):
        if path.is_file():
            data = path.read_bytes()
            tables[path.name] = {'sha256': STAGE.digest(data), 'bytes': len(data),
                                 'signature': data[:4].decode('ascii', errors='replace'),
                                 'oem_identity': data[10:24].decode('ascii', errors='replace')}
    asus = [table['sha256'] for table in tables.values()
            if table['signature'] == 'SSDT' and table['oem_identity'] == '_ASUS_ASUSSSDT']
    observed = 'unknown'
    if asus == [STAGE.POLICY.REFERENCE_SHA256]:
        observed = 'legacy'
    elif asus == [NATIVE_SSDT]:
        observed = 'native'
    dsp = {str(path.parent): read(path)
           for path in Path('/sys/bus/platform/drivers/n1x-adsp').glob('*/status')}
    gates = {'kernel_matches': os.uname().release == manifest['source_kernel'],
             'command_line_matches': command == expected_command,
             'acpi_profile_matches': observed == phase,
             'no_published_dsp': all(isinstance(status, str) and
                                     'published=0' in status.split() for status in dsp.values())}
    logs = subprocess.run(['journalctl', '-k', '-b', '--no-pager', '-o', 'short-monotonic'],
                          text=True, capture_output=True, timeout=30)
    if logs.returncode:
        raise ValueError('Cannot collect kernel journal: ' + logs.stderr)
    report = {'captured_at': datetime.now(timezone.utc).isoformat(),
              'boot_id': read('/proc/sys/kernel/random/boot_id'), 'kernel': os.uname().release,
              'bios': read('/sys/class/dmi/id/bios_version'), 'command_line': command,
              'requested_phase': phase, 'observed_acpi_profile': observed,
              'candidate_manifest_sha256': STAGE.digest((candidate_dir / 'manifest.json').read_bytes()),
              'comparison_gates': gates, 'comparison_admitted': all(gates.values()),
              'dsp': dsp, 'tables': tables, 'power_state': power_state(),
              'modules': {path.name: {'version': read(path / 'version'),
                                     'srcversion': read(path / 'srcversion')}
                          for path in Path('/sys/module').glob('*')
                          if path.name in ('n1x_adsp', 'n1x_npu_bootstrap', 'snd_soc_mt8901_afe',
                                           'asus_wmi', 'asus_nb_wmi', 'spark_hwmon')},
              'hardware_qualified': False,
              'physical_tests': 'Not performed by this read-only collector: AC disconnect/reconnect, '
                                'threshold/profile changes, sustained activity and suspend/resume.'}
    output.mkdir(mode=0o700, parents=False)
    paths = [output / 'report.json', output / 'kernel.log']
    paths[0].write_text(json.dumps(report, indent=2) + '\n')
    paths[1].write_text(logs.stdout)
    if os.geteuid() == 0 and 'PKEXEC_UID' in os.environ:
        owner = pwd.getpwuid(int(os.environ['PKEXEC_UID']))
        for path in (*paths, output):
            os.chown(path, owner.pw_uid, owner.pw_gid)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--phase', choices=('legacy', 'native'), required=True)
    parser.add_argument('--output', type=Path, required=True, help='new report directory')
    args = parser.parse_args()
    try:
        report = collect(args.candidate, args.phase, args.output)
        print(json.dumps(report['comparison_gates'], indent=2))
        if not report['comparison_admitted']:
            parser.exit(1, 'Recorded observations only: this boot is not an admitted comparison baseline\n')
        print('Snapshot recorded; physical qualification remains pending')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')
