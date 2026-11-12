#!/usr/bin/env python3
"""Stage early-console diagnostics without changing kernel, initrd or boot files."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess

_spec = importlib.util.spec_from_file_location('audio_boot_stage', Path(__file__).with_name('stage-native-acpi.py'))
STAGE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(STAGE)
BOOT = STAGE.BOOT

DIAGNOSTICS = ('efi=debug', 'earlycon=efifb', 'keep_bootcon', 'loglevel=8', 'initcall_debug',
               'log_buf_len=4M', 'rd.log=kmsg,file', 'systemd.show_status=true',
               'printk.time=1', 'panic=0')
KEYS = {argument.split('=', 1)[0] for argument in DIAGNOSTICS}


def diagnostic_cmdline(original):
    arguments = shlex.split(original)
    if not {'acpi=nospcr', 'acpi_osi=!Windows 2022'} <= set(arguments):
        raise ValueError('Expected the existing N1X console and ACPI quirks')
    if any(arg.startswith('efi=') and arg != 'efi=debug' for arg in arguments):
        raise ValueError('Preserve non-debug EFI policy separately')
    # Edit whole unquoted diagnostic tokens only. In particular, preserve the
    # double-quoted Windows OSI argument as Linux expects it, not shell quoting.
    names = '|'.join(re.escape(key) for key in sorted(KEYS | {'quiet', 'splash'}))
    line = re.sub(r'(?<!\S)(?:'+names+r')(?:=[^\s]+)?(?=\s|$)', '', original).strip()
    line += ' ' + ' '.join(DIAGNOSTICS)
    before = [arg for arg in arguments if arg.split('=', 1)[0] not in KEYS | {'quiet', 'splash'}]
    after = [arg for arg in shlex.split(line) if arg.split('=', 1)[0] not in KEYS]
    if before != after:
        raise ValueError('A non-diagnostic kernel argument changed')
    return line + '\n'


def stage(source, directory):
    source = source.resolve(strict=True)
    directory = directory.resolve()
    if directory.exists() or any(directory.is_relative_to(Path(p)) for p in ('/boot', '/efi')):
        raise ValueError('Choose a new private staging directory outside the boot partitions')
    raw = source.read_bytes()
    sections = BOOT.sections(source)
    STAGE.require_unsigned(raw, sections)
    layout = STAGE.section_layout(raw)
    command = diagnostic_cmdline(sections['.cmdline'].rstrip(b'\0').decode()).encode()
    address = layout['.cmdline'][0]
    following = [item[0] for item in layout.values() if item[0] > address]
    if not following or address + len(command) > min(following):
        raise ValueError('Diagnostic command line would overlap the next PE section')
    directory.mkdir(parents=True, mode=0o700)
    snapshot, command_file = directory/'source.efi', directory/'cmdline'
    snapshot.write_bytes(raw)
    command_file.write_bytes(command)
    candidate = directory/'audio-boot-diagnostics.efi'
    # BFD update-section retains the old PE VirtualSize when growing this
    # section. Re-add it at its existing address, as in the ACPI staging tool.
    subprocess.run(['objcopy', '--remove-section', '.cmdline',
                    '--add-section', '.cmdline='+str(command_file),
                    '--change-section-vma', '.cmdline='+hex(address),
                    '--set-section-flags', '.cmdline=alloc,load,readonly,data',
                    str(snapshot), str(candidate)], check=True)
    result = BOOT.sections(candidate)
    if set(result) != set(sections) or STAGE.section_layout(candidate.read_bytes()) != layout or \
            any(result[name] != data for name, data in sections.items() if name != '.cmdline') or \
            result['.cmdline'] != command:
        raise ValueError('Unexpected change outside the diagnostic command line')
    BOOT.verify_image(candidate)
    manifest = {'source_sha256': hashlib.sha256(raw).hexdigest(),
                'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
                'kernel_release': result['.uname'].rstrip(b'\0\n').decode(),
                'cmdline': command.decode().strip(),
                'unchanged_sections': {n: hashlib.sha256(v).hexdigest() for n, v in sections.items() if n != '.cmdline'},
                'purpose': 'Capture the N1X physical boot failure; not a boot fix',
                'hardware_qualified': False, 'boot_files_written': False}
    (directory/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(directory/'manifest.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    stage(args.source, args.output)


if __name__ == '__main__':
    main()
