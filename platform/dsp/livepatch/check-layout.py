#!/usr/bin/env python3
"""Read-only BTF comparison for the temporary kernel31 AFE migration."""
import argparse
import ctypes as c
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('btf', ROOT / 'scripts/verify-module-btf.py')
btf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(btf)
NAMES = ('mt8901_afe_sram', 'mt8901_afe_sram_buffer', 'mt8901_afe_private',
         'mtk_base_afe', 'mtk_base_afe_memif', 'mt8901_afe_sram_endpoint')


def layout(checker, path):
    lib = checker.lib
    data = btf.sections(path)
    embedded = None
    module = None
    try:
        base = checker.base
        if '.BTF.base' in data:
            raw = data['.BTF.base']
            embedded = checker.require(lib.btf__new(raw, len(raw)), path)
            base = embedded
        raw = data['.BTF']
        module = checker.require(lib.btf__new_split(raw, len(raw), base), path)
        if embedded and lib.btf__relocate(module, checker.base):
            raise RuntimeError('BTF relocation failed: ' + str(path))
        report = {}
        for name in NAMES:
            ident = lib.btf__find_by_name_kind(module, name.encode(), 4)
            if ident <= 0:
                raise RuntimeError('Missing structure: ' + name)
            item = lib.btf__type_by_id(module, ident)
            members = c.cast(c.addressof(item.contents) + 12, c.POINTER(c.c_uint32))
            fields = []
            for index in range(item[1] & 65535):
                offset, ref, bits = members[3 * index:3 * index + 3]
                fields.append((lib.btf__name_by_offset(module, offset).decode(), bits,
                               lib.btf__resolve_size(module, ref)))
            report[name] = {'bytes': item[2], 'fields': fields}
        return report
    finally:
        if module:
            lib.btf__free(module)
        if embedded:
            lib.btf__free(embedded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vmlinux', type=Path, required=True)
    parser.add_argument('--afe', type=Path, required=True)
    parser.add_argument('--livepatch', type=Path, required=True)
    args = parser.parse_args()
    checker = btf.Checker(args.vmlinux)
    try:
        for name, arguments, result in (
            ('btf__find_by_name_kind', [c.c_void_p, c.c_char_p, c.c_uint32], c.c_int),
            ('btf__type_by_id', [c.c_void_p, c.c_uint32], c.POINTER(c.c_uint32)),
            ('btf__name_by_offset', [c.c_void_p, c.c_uint32], c.c_char_p),
            ('btf__resolve_size', [c.c_void_p, c.c_uint32], c.c_long),
        ):
            function = getattr(checker.lib, name)
            function.argtypes, function.restype = arguments, result
        expected = layout(checker, args.afe)
        if expected != layout(checker, args.livepatch):
            raise RuntimeError('Private AFE structure layouts differ; do not load the livepatch')
        print(json.dumps(expected, indent=2))
    finally:
        checker.close()


if __name__ == '__main__':
    main()
