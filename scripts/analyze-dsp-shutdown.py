#!/usr/bin/env python3
"""Extract pinned native loader cleanup and power-query instructions without execution."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct

import capstone
import pefile

INPUTS = {
    'sroot': {
        'sha256': 'f814e861b5e076aa4e00619a8a588df3c4ae9ec2b5026c30748ba493ce0e6d8a',
        'functions': {
            'image_copy': (0x39b0, 0x3b08),
            'image_allocate': (0x3b08, 0x3e00),
            'image_free': (0x3e00, 0x3f80),
            'upload': (0x31c98, 0x321c0),
        },
    },
    'pep': {
        'sha256': '34cf1f2a9372a092555fb0887bfb76a8f205a76ff7e557224b353b09497c9bb1',
        'functions': {
            'query_wrapper': (0x16ca8, 0x16f18),
            'device_probe': (0x1ee60, 0x1f390),
            'device_power_state': (0x1fb40, 0x1ff38),
            'tinysys_get': (0x43748, 0x439b8),
        },
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sroot', required=True, type=Path)
    parser.add_argument('--pep', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output directory to preserve prior evidence')
    images = {}
    for name, reference in INPUTS.items():
        data = getattr(args, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != reference['sha256']:
            parser.error('Input differs from pinned ' + name + ' binary')
        pe = pefile.PE(data=data)
        if pe.FILE_HEADER.Machine != 0xaa64 or pe.OPTIONAL_HEADER.ImageBase != 0x140000000:
            parser.error('Unexpected PE architecture or image base')
        images[name] = pe.get_memory_mapped_image()
    constants = struct.unpack_from('<4I', images['pep'], 0x439b8)
    if constants != (0x20004, 0, 1, 16):
        parser.error('Unexpected TINYSYS GET constants')
    cs = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    instructions = {}
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'hardware_requests_sent': False, 'binaries_executed': False,
              'inputs': {}, 'functions': {}}
    for name, reference in INPUTS.items():
        report['inputs'][name] = reference['sha256']
        for function, (start, end) in reference['functions'].items():
            key = name + '_' + function
            raw = images[name][start:end]
            decoded = list(cs.disasm(raw, 0x140000000 + start))
            if len(decoded) * 4 != len(raw):
                parser.error('Incomplete instruction decode: ' + key)
            instructions[key] = decoded
            report['functions'][key] = {'start': hex(0x140000000 + start),
                                        'end': hex(0x140000000 + end),
                                        'sha256': hashlib.sha256(raw).hexdigest()}
    calls = [(instruction.address, int(instruction.op_str.removeprefix('#'), 16))
             for instruction in instructions['sroot_upload'] if instruction.mnemonic == 'bl']
    expected = [0x140003b08, 0x1400039b0, 0x140005580, 0x140003e00]
    filtered = [(address, target) for address, target in calls if target in expected]
    if [target for _, target in filtered] != expected:
        parser.error('Unexpected upload allocation/copy/exchange/free call order')
    if not any(i.mnemonic == 'ldr' and i.op_str == 'x8, [x8, #0x18]'
               for i in instructions['sroot_image_free']):
        parser.error('Missing DMA_OPERATIONS FreeCommonBuffer table slot')
    if not any(i.mnemonic == 'mov' and i.op_str == 'w8, #0x18'
               for i in instructions['sroot_upload']):
        parser.error('Missing upload command ID')
    report['loader_staging'] = {
        'command': '0x18',
        'calls': [{'instruction': hex(address), 'target': hex(target)}
                  for address, target in filtered],
        'free_operation_offset': '0x18',
        'free_parameters': 'Adapter, full allocation length, DMA address, CPU address, uncached',
        'reference': 'https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/ns-wdm-_dma_operations',
        'scope': 'Temporary image buffer; not DSP operating DRAM or AFE SRAM',
        'native_error_cleanup_not_adopted': True,
        'linux_release_gate': 'v2 only: completed exchange with canonical header 0x18 and no payload/status/detail',
        'linux_hardware_release_qualified': False,
    }
    report['retention_candidate'] = {
        'device_power_state': '0x14001fb40',
        'tinysys_set_wrapper': '0x1400169d0',
        'composite': 'ACPI action | (DevicePowerState << 16) | (Complete << 8) | SystemStateTransition',
        'linux_d3': 'mtk_pwrap_dev_suspend(pwrap, 1)',
        'linux_d0': 'mtk_pwrap_dev_resume(pwrap, 1)',
        'hardware_qualified': False,
        'limitations': 'SET acknowledgement is not proof of DSP DMA quiescence or full firmware state retention; no DSP memory/lease may be released',
    }
    report['power_query'] = {
        'message_id': 4, 'protocol': '0x80', 'flags': 1, 'length': 16,
        'reply_words': ['context+0x200', 'context+0x204', 'context+0x208'],
        'caller': 'Device probe; wrapper result is logged',
        'dsp_dma_off_interpretation_verified': False,
        'linux_get_request_sent': False,
    }
    report['remaining'] = ['Verified DSP core quiesce and power-off completion',
                           'Operating DRAM/AFE SRAM and provider-lease release',
                           'Fresh-boot hardware qualification of loader staging release']
    args.output.mkdir(parents=True)
    for key, decoded in instructions.items():
        (args.output / (key + '.asm')).write_text(''.join(
            f'{i.address:016x}: {i.bytes.hex():8s}  {i.mnemonic:8s} {i.op_str}\n' for i in decoded))
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(args.output / 'report.json')


if __name__ == '__main__':
    main()
