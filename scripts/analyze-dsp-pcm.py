#!/usr/bin/env python3
"""Extract pinned ARM64 instructions supporting the DSP PCM descriptor layout.

Requires pefile and capstone. This reads the PE without executing its code.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import struct
from pathlib import Path

import capstone
import pefile

NATIVE_SHA256 = 'a3eaa49ea54b1a7511542091efbd527000aeff4148753e68f179077c539224de'
MAILBOX_SHA256 = '8b21e4652bb0ac178a2c470c8d6f982155e715c46112ac3b93de3ebfe00b13d6'
FUNCTIONS = {
    'sram_mapping': (0x140024560, 0x140024998),
    'sram_address_translation': (0x140025fe0, 0x1400262c0),
    'host_message_tasks': (0x140023de0, 0x140023e30),
    'processing_message_tasks': (0x140024998, 0x1400249e8),
    'message_allocate': (0x1400249e8, 0x140025020),
    'message_register': (0x140025020, 0x140025920),
    'clear_descriptor': (0x140006680, 0x1400066b8),
    'initialize_ring': (0x1400066b8, 0x140006708),
    'write_ring_update': (0x140006938, 0x140006b90),
    'stream_constructor': (0x140027ba8, 0x1400288b0),
    'processing_select': (0x140027438, 0x140027ba8),
    'stream_open': (0x1400288b0, 0x140028f40),
    'stream_close': (0x140028f40, 0x140029310),
    'stream_start': (0x140029310, 0x140029a50),
    'stream_pause': (0x14002ab70, 0x14002aed8),
    'stream_resume': (0x14002a8a0, 0x14002ab70),
    'scalar_command': (0x14002c328, 0x14002c3d8),
    'empty_command': (0x14002c288, 0x14002c328),
    'task_qos_acquire': (0x14002d0d8, 0x14002d488),
    'task_qos_release': (0x14002d488, 0x14002d700),
    'memif_users_get': (0x14000a1c8, 0x14000a330),
    'memif_users_increment': (0x14000a568, 0x14000a6d8),
    'memif_users_decrement': (0x14000a6d8, 0x14000a848),
    'afe_channel_merge_enable': (0x1400076f8, 0x1400077e8),
    'afe_channel_merge_disable': (0x1400077e8, 0x140007960),
    'afe_gain_enable': (0x14000ccb8, 0x14000ce50),
    'afe_gain_disable': (0x14000ce50, 0x14000cf88),
    'afe_gain_users': (0x14000c2a0, 0x14000c380),
    'afe_gain_bit_enable': (0x14000c440, 0x14000c4c0),
    'afe_gain_bit_disable': (0x14000c4c0, 0x14000c590),
    'afe_irq_parameters': (0x14003c390, 0x14003c400),
    'afe_irq_prepare_entry': (0x140016150, 0x140016188),
    'afe_irq_prepare_once': (0x1400091d8, 0x1400092b0),
    'afe_irq_configure': (0x140008e80, 0x140008fd0),
    'afe_dsp_irq_open': (0x1400267e8, 0x140026830),
    'afe_dsp_irq_reference': (0x140026830, 0x1400268b0),
    'afe_dsp_irq_stop': (0x1400268b0, 0x140026a90),
    'afe_memif_constructor': (0x14003d290, 0x14003de68),
    'speaker_start': (0x140083a10, 0x1400841a0),
    'speaker_stop': (0x1400841a0, 0x1400844d0),
    'speaker_irq_create': (0x140085e88, 0x140086648),
    'stream_stop': (0x140029a50, 0x14002a0b0),
    'configure': (0x14002a0b0, 0x14002a8a0),
    'direction': (0x14002aed8, 0x14002afc0),
    'host_hwparam': (0x14002afc0, 0x14002b368),
    'prepare_record_select': (0x14002b368, 0x14002b3b8),
    'prepare_afe': (0x14002b3b8, 0x14002b5b0),
    'prepare_host': (0x14002b5b0, 0x14002b870),
    'pcm_notification': (0x14002b9e0, 0x14002bf70),
    'memif_task_first': (0x14002c1a8, 0x14002c288),
    'memif_task_insert': (0x14002c490, 0x14002c650),
    'publish_write_position': (0x14002cc80, 0x14002ce90),
    'publish_write_position_resume': (0x14002ce90, 0x14002d0d8),
    'producer_wrappers': (0x14006c3b0, 0x14006c420),
    'memif_to_irq': (0x14003c248, 0x14003c2f0),
    'runtime_routing': (0x140052840, 0x140053ab8),
    'create_stream': (0x140044010, 0x140044d48),
    'endpoint_defaults': (0x14004f520, 0x14004f5d0),
    'common_constructor': (0x14005cc68, 0x14005cef0),
    'speaker_setup': (0x140085358, 0x140085e88),
    'engine_prepare': (0x1400d5750, 0x1400d5e10),
    'task_core_mapping': (0x140006ed0, 0x140006f20),
    'microphone_stream_setup': (0x1400810e8, 0x1400819f0),
    'microphone_irq_create': (0x1400819f0, 0x140082188),
    'microphone_input_routes': (0x140082188, 0x140082ac8),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mailbox-binary', type=Path)
    args = parser.parse_args()
    data = args.binary.read_bytes()
    if hashlib.sha256(data).hexdigest() != NATIVE_SHA256:
        parser.error('The binary differs from the pinned nvasd.sys')
    if args.output.exists():
        parser.error('Use a new output directory to preserve previous evidence')
    pe = pefile.PE(data=data)
    if pe.FILE_HEADER.Machine != 0xaa64 or pe.OPTIONAL_HEADER.ImageBase != 0x140000000:
        parser.error('Unexpected PE architecture or image base')
    image = pe.get_memory_mapped_image()
    producer_vtable = {}
    for offset, expected in [(0xc8, 0x14002cc80), (0xd0, 0x14002ce90)]:
        address = int.from_bytes(image[0xb5570 + offset:0xb5578 + offset], 'little')
        if address != expected:
            parser.error('Unexpected producer-method vtable target')
        producer_vtable[hex(offset)] = hex(address)
    transition_vtable = {}
    for offset, name, expected in [
            (0x18, 'start', 0x140029310), (0x20, 'stop', 0x140029a50),
            (0x38, 'pause', 0x14002ab70), (0x40, 'resume', 0x14002a8a0)]:
        address = int.from_bytes(image[0xb5570 + offset:0xb5578 + offset], 'little')
        if address != expected:
            parser.error('Unexpected stream-transition vtable target')
        transition_vtable[name] = {'offset': hex(offset), 'target': hex(address)}
    irq_records = {}
    for index in range(22):
        start = 0xab040 + index * 0x40
        fields = struct.unpack_from('<16I', image, start)
        # The pinned native IRQ-12 record reuses IRQ-11 register offsets.
        cfg = 0x9d98 if index == 12 else 0x9d40 + index * 8
        expected = (cfg + 4, 0, 0xffffff, cfg, 4, 0x1f,
                    cfg, 0, cfg + 4, 31, index, cfg, 9, 7, 0x9d00, index)
        if fields != expected:
            parser.error('Unexpected MT8901 IRQ descriptor')
        irq_records[str(index)] = {'address': hex(0x140000000 + start),
                                   'counter': {'register': hex(fields[0]), 'shift': fields[1], 'mask': hex(fields[2])},
                                   'rate': {'register': hex(fields[3]), 'shift': fields[4], 'mask': hex(fields[5])},
                                   'enable': {'register': hex(fields[6]), 'shift': fields[7]},
                                   'domain': {'register': hex(fields[11]), 'shift': fields[12], 'mask': hex(fields[13])}}
    gain_enable = struct.unpack_from('<3I', image, 0xac240 + 0x18)
    if gain_enable != (0x9800, 16, 1):
        parser.error('Unexpected gain-enable descriptor')
    irq_vtable = {}
    for offset, expected in [(8, 0x140026830), (0x10, 0x1400268b0), (0x18, 0x140016150)]:
        target = int.from_bytes(image[0xb5548 + offset:0xb5550 + offset], 'little')
        if target != expected:
            parser.error('Unexpected DSP IRQ vtable target')
        irq_vtable[hex(offset)] = hex(target)
    record_selection = {}
    for task in range(7, 41):
        displacement = int.from_bytes(image[0x2b394 + task - 7:0x2b395 + task - 7],
                                      'little', signed=True)
        branch = 0x14002b394 + displacement * 4
        if branch not in (0x14002b384, 0x14002b38c):
            parser.error('Unexpected prepare-record selection branch')
        record_selection[str(task)] = {'branch': hex(branch),
                                       'first_record': branch == 0x14002b384}
    if not record_selection['7']['first_record']:
        parser.error('Task 7 does not select the host descriptor')
    if record_selection['16']['first_record']:
        parser.error('Task 16 does not select the hardware descriptor')
    sram_mask = int.from_bytes(image[0x25018:0x2501c], 'little')
    if sram_mask != 0x20010400:
        parser.error('Unexpected task-message SRAM mask')
    table = image[0xc5990:0xc5990 + 41 * 0x210]
    if len(table) != 41 * 0x210 or any(table):
        parser.error('Unexpected initial task-descriptor storage')
    disassembler = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    mailbox = None
    if args.mailbox_binary:
        mailbox_data = args.mailbox_binary.read_bytes()
        if hashlib.sha256(mailbox_data).hexdigest() != MAILBOX_SHA256:
            parser.error('The binary differs from the pinned nvadsp.sys')
        mailbox = pefile.PE(data=mailbox_data)
        if mailbox.FILE_HEADER.Machine != 0xaa64 or mailbox.OPTIONAL_HEADER.ImageBase != 0x140000000:
            parser.error('Unexpected mailbox PE architecture or image base')
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'binary_sha256': NATIVE_SHA256, 'hardware_commands_sent': False,
              'functions': {}, 'initial_task_records_zero': True,
              'acx_function_table': {
                  'base': '0x1400cc1e0',
                  'reference': 'https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/acxfuncenum/ne-acxfuncenum-acxfuncenum',
                  'getters': {'channels': {'index': 43, 'pointer': '0x1400cc338'},
                              'container_bits': {'index': 46, 'pointer': '0x1400cc350'},
                              'valid_bits': {'index': 47, 'pointer': '0x1400cc358'},
                              'rate': {'index': 50, 'pointer': '0x1400cc370'}}},
              'descriptor': {
                  'bytes': 96, 'format_word': 'container bits; no ALSA enum conversion',
                  'format_trace': ['AcxDataFormatGetBitsPerSample -> engine_prepare local_184',
                                   'create_stream local_208 -> common_constructor +0x18',
                                   'speaker_setup local_140 at parameter+0x58 -> stream_constructor +0xe8',
                                   'configure +0xe8 -> temporary+0x20',
                                   'host_hwparam 0x14002b084..0x14002b088 -> descriptor+0x30'],
                  'tail': {'0x50': 'host 0, hardware 1', '0x51': 'hardware memif ID',
                           '0x52': 'hardware IRQ ID; reference maps IDs 0..15 identically',
                           '0x53': 'wire value 1 for both host and hardware buffers',
                           '0x54': 'counter; initial task storage is zero',
                           '0x58': 'ignore_irq; initial task storage is zero'},
                  'tail_instruction_ranges': ['0x14002b070..0x14002b078',
                                              '0x14002a544..0x14002a54c',
                                              '0x14002a65c..0x14002a66c'],
                  'native_primary_direction': 1,
                  'default_hardware_period_frames': 480, 'default_hardware_periods': 2},
              'allocation_selector_trace': {
                  'default': 3,
                  'default_initializer': '0x14004f520: first-endpoint selectors at SoC offsets 0x2870/0x4b98/0x6ec0/0x91e8; stride 0x9304',
                  'create_stream': 'mode selects endpoint table entry -> local_68',
                  'common_constructor': 'parameter+0x1d8 -> stream object+0x218',
                  'speaker_setup': 'stream object+0x218 -> constructor parameter+0x84',
                  'stream_constructor': 'parameter+0x84 -> context+0x1b4; selector 3 uses AFE pool 0',
                  'qualification': 'Static default path; not a live Windows endpoint observation'},
              'sram_mapping': {'native_api': 'MmMapIoSpace(physical, bytes, 0)',
                               'cache_type': 'MmNonCached (0)',
                               'linux_api': 'devm_ioremap_resource; no write combining',
                               'translation': '0x140025fe0: selector 2 -> context+0x50 (AFE/VAD), selectors 3/4 -> context+0x58 (HiFi5); 0x1400249e8 maps task-core 3 -> selector 2, task-core 1 -> selector 3' },
              'prepare': {'configure_call_order': ['0x14002a7c0: primary AFE prepare helper',
                                                  '0x14002a7cc: primary host prepare helper'],
                          'afe_command': '0x203', 'host_command': '3',
                          'inline_bytes': 8, 'descriptor_bytes': 96,
                          'task7_record': 'prepare_record_select returns 1 for task 7; both helpers copy the first (host) descriptor, not the hardware descriptor',
                          'record_selection_table': record_selection,
                          'resume_parameter2': '0 for initial prepare; resume path is separate',
                          'hardware_validated': False},
              'primary_pipeline': {
                  'route': 2, 'core': 'HiFi1; native core enum 3',
                  'primary_task': 7, 'processing_task': 16,
                  'selection': 'primary uses first free 7..9; per-memif processing list uses first free 16..17',
                  'processing_message_commands': [5, 6],
                  'processing_message_sram_mask': hex(sram_mask),
                  'processing_message_view': 'native translation selector 2 (AFE/VAD)',
                  'configuration': [[7, 4, 'host'], [16, 0x201, 'hardware'], [16, 4, 'bridge']],
                  'prepare': [[16, 0x203, 'hardware'], [16, 3, 'bridge'], [7, 0x203, 'host'], [7, 3, 'host']],
                  'close': [[7, 9, 0], [7, 2, 0], [16, 9, 0], [16, 0x202, 1], [16, 2, 0]],
                  'qualification': 'Static route-2 single-processing-task path; no stream executed'},
              'period_notification': {
                  'class': 0, 'ack_mode': 0, 'channel': 7, 'command': '0x1b',
                  'read_pointer_packet_offset': '0x30',
                  'counter_packet_offset': '0x74',
                  'counter': 'CPU write-publication generation echoed by DSP; not a period count',
                  'native_nonzero_parameter2': 'ignored before copying the read pointer',
                  'linux_inline_policy': 'data_mode 1 and 96..256 payload bytes; bounds policy, not hardware qualification',
                  'hardware_validated': False},
              'stream_transitions': {
                  'vtable': {'base': '0x1400b5570', 'methods': transition_vtable},
                  'scope': 'Route-2 playback, one primary and one processing task, fresh non-paused start; static analysis only',
                  'mode': 'stream context +0xbc, copied from constructor parameter +0x30; this is not the memif ID or route',
                  'start_first_user': [
                      'Increment memif users and DSP users; fresh memif count becomes 1',
                      'For each processing task: QoS acquire, command 0x0f with parameters (0, mode)',
                      'Enable the optional channel-merge owner at context +0x98 and hardware-gain owner at +0xa8',
                      'Primary task QoS acquire, command 0x0f with parameters (mode, first processing task)'],
                  'stop_last_user': [
                      'Primary task command 0x10 (no payload), QoS release',
                      'Decrement memif and DSP users',
                      'For processing tasks in configured stop order: command 0x10 (no payload), QoS release',
                      'Disable the optional channel-merge and hardware-gain owners'],
                  'other_transitions': {
                      'resume': 'command 0x209; processing parameter2=mode, primary parameter2=first processing task',
                      'pause': 'command 0x206; does not follow the complete normal STOP hardware-disable path',
                      'already_active_memif': 'Normal start has a separate 0x209 branch when the shared memif is already active; not a fresh single-stream START'},
                  'hardware_owner_note': 'Context +0x98 owns a channel merge; +0xa8 owns hardware gain, not IRQ. Gain descriptor 0x1400ac240 enables AFE_GAIN_DL0_CON0 (0x9800), bit 16. The separate speaker IRQ object is at +0x2a8.',
                  'correction': 'Earlier extracts named 0x14002a8a0 stream_start; it is the distinct vtable +0x40 resume transition. Preserve old receipts as superseded evidence.',
                  'remaining': ['Hardware qualification of Linux SRAM address and IRQ preparation',
                                'Connect the Linux stream endpoint and correct memif, hardware-gain and separate DSP IRQ ownership',
                                'Hardware qualification; task STOP does not prove whole-core DMA quiescence'],
                  'hardware_validated': False},
              'afe_irq_and_gain_owners': {
                  'corrects': 'dsp-stream-transitions-qualified-analysis misidentified stream +0xa8 as IRQ; it is hardware gain',
                  'gain': {'descriptor': '0x1400ac240', 'enable_register': hex(gain_enable[0]),
                           'enable_shift': gain_enable[1], 'enable_mask': gain_enable[2],
                           'native_source_name': 'afe_common/afe_memif_hwgain.cpp',
                           'stream_context': '+0xa8'},
                  'irq': {'descriptors': irq_records, 'descriptor_table_sha256': hashlib.sha256(image[0xab040:0xab040 + 22 * 0x40]).hexdigest(),
                          'native_descriptor_anomaly': 'IRQ 12 reuses IRQ 11 register offsets; P16 candidate playback uses IRQs 0..6 and does not copy this anomaly',
                          'speaker_context': '+0x2a8', 'vtable': {'base': '0x1400b5548', 'methods': irq_vtable},
                          'prepare': '0x140016150 -> 0x1400091d8 -> 0x140008e80; period counter, rate, domain; does not enable IRQ',
                          'start': '0x140026830 increments the native IRQ reference count without writing the enable or target register',
                          'stop': '0x1400268b0 uses the endpoint route: 2 -> 0xa000 (HiFi1), 3 -> 0x9d04 (primary HiFi5), 4 -> 0x9d08. This enum is distinct from the task-core selector.',
                          'speaker_start_order': '0x140083a10: IRQ prepare (+0x18), DSP stream START (+0x18), IRQ reference (+8)',
                          'speaker_stop_order': '0x1400841a0: DSP stream STOP (+0x20), IRQ stop (+0x10)'},
                  'hardware_validated': False},
              'producer_publication': {
                  'vtable': {'base': '0x1400b5570', 'methods': producer_vtable},
                  'descriptor_source': 'task record +0x60',
                  'message_cpu_pointer': 'task record +0x158 (command-5 message buffer)',
                  'bytes': 96, 'mailbox_command': None,
                  'write_pointer': 'ring base plus caller byte offset; end boundary preserved',
                  'read_pointer': 'last consumed pointer retained in the host record',
                  'generation': 'context +0xc0 copied to descriptor +0x54, then advanced; INT_MAX wraps to zero',
                  'hardware_validated': False},
              'capture': {
                  'endpoint': 'microphone path 3; primary HiFi5 task-core selector 1',
                  'descriptor_direction': '0x14002aed8 returns 2 for tasks 23/21; 0x14002a0b0 clears capture start threshold to zero',
                  'host_task': 23, 'raw_host_task': 22, 'processing_task': 21,
                  'mode_selection': '0x140027ba8 compares nonzero processing-mode GUID to RAW 9e90ea20-b493-4fd1-a1a8-7e1361a956cf; RAW -> 22, other nonzero modes -> 23',
                  'messages': 'host 23: 5/6/0x20a/0x20b; processing 21: 5/6; all six messages use operating DRAM, not SRAM',
                  'start': [[21, 15, 0, 1], [23, 31, 21, 0], [23, 17, 48, 0], [23, 15, 1, 21]],
                  'notification': 'class 0, ACK 0, task 23, command 0x13; inline 96-byte descriptor; producer at packet +0x38',
                  'counter': 'native IRQUL does not apply the DL_CONSUME_DATA generation filter',
                  'irq_enum_trace': 'create_stream local_c0=endpoint path -> parameter+0x180 -> common_constructor context+0x198 -> microphone_irq_create +0x2f4 -> DSP IRQ constructor+0x34 -> stop target selection',
                  'hardware_validated': False,
              },
              'remaining': ['Fresh-boot duplex/endpoint and system-sleep hardware qualification',
                            'Actual stream workload and verified core shutdown/DMA release']}
    args.output.mkdir(parents=True)
    if mailbox:
        start, end = 0x140005980, 0x140006220
        block = mailbox.get_memory_mapped_image()[start - 0x140000000:end - 0x140000000]
        name = 'mailbox_receive_worker.asm'
        instructions = '\n'.join(f'{inst.address:x}: {inst.mnemonic} {inst.op_str}'
                                 for inst in disassembler.disasm(block, start)) + '\n'
        (args.output / name).write_text(instructions)
        report['mailbox_notification_dispatch'] = {
            'binary_sha256': MAILBOX_SHA256, 'start': hex(start), 'end_exclusive': hex(end),
            'binary_range_sha256': hashlib.sha256(block).hexdigest(), 'disassembly': name,
            'classification': 'class 0 / ACK 2 completes transactions; class 0 / ACK 0 dispatches client notifications'}
    for name, (start, end) in FUNCTIONS.items():
        block = image[start - pe.OPTIONAL_HEADER.ImageBase:end - pe.OPTIONAL_HEADER.ImageBase]
        if len(block) != end - start:
            raise ValueError('Truncated code: ' + name)
        instructions = '\n'.join(f'{inst.address:x}: {inst.mnemonic} {inst.op_str}'
                                 for inst in disassembler.disasm(block, start)) + '\n'
        (args.output / (name + '.asm')).write_text(instructions)
        report['functions'][name] = {'start': hex(start), 'end_exclusive': hex(end),
                                     'binary_sha256': hashlib.sha256(block).hexdigest(),
                                     'disassembly': name + '.asm'}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(args.output / 'report.json')


if __name__ == '__main__':
    main()
