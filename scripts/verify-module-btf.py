#!/usr/bin/env python3
"""Check module split BTF against the exact candidate kernel, without loading it."""
import argparse
import ctypes
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import struct
import subprocess
import sys


def sections(path):
    raw = path.read_bytes()
    if path.suffix == '.xz':
        raw = lzma.decompress(raw)
    elif path.suffix == '.gz':
        raw = gzip.decompress(raw)
    elif path.suffix == '.zst':
        raw = subprocess.check_output(['zstd', '-dq', '-c', str(path)])
    if len(raw) < 64 or raw[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected a little-endian ELF64 module: ' + str(path))
    offset = struct.unpack_from('<Q', raw, 40)[0]
    size, count, names = struct.unpack_from('<HHH', raw, 58)
    if size != 64 or not count or names >= count or offset + size * count > len(raw):
        raise ValueError('Invalid ELF section table: ' + str(path))
    headers = [struct.unpack_from('<IIQQQQIIQQ', raw, offset + i * size) for i in range(count)]
    header = headers[names]
    table = raw[header[4]:header[4] + header[5]]
    result = {}
    for header in headers:
        start = header[0]
        end = table.find(b'\0', start)
        if end < 0:
            raise ValueError('Invalid ELF section name: ' + str(path))
        name = table[start:end].decode()
        if name in ('.BTF', '.BTF.base'):
            start, length = header[4:6]
            if start + length > len(raw) or name in result:
                raise ValueError('Invalid BTF section: ' + str(path))
            result[name] = raw[start:start + length]
    return result


class Checker:
    def __init__(self, vmlinux, kernel_image=None):
        self.lib = ctypes.CDLL('libbpf.so.1', use_errno=True)
        pointer = ctypes.c_void_p
        for name, args, result in (
            ('btf__parse_elf', [ctypes.c_char_p, pointer], pointer),
            ('btf__new', [pointer, ctypes.c_uint32], pointer),
            ('btf__new_split', [pointer, ctypes.c_uint32, pointer], pointer),
            ('btf__relocate', [pointer, pointer], ctypes.c_int),
            ('btf__raw_data', [pointer, ctypes.POINTER(ctypes.c_uint32)], pointer),
            ('libbpf_get_error', [pointer], ctypes.c_long),
            ('btf__free', [pointer], None),
        ):
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        self.base = self.require(self.lib.btf__parse_elf(str(vmlinux).encode(), None), vmlinux)
        size = ctypes.c_uint32()
        pointer = self.lib.btf__raw_data(self.base, ctypes.byref(size))
        if not pointer:
            self.close()
            raise ValueError('Cannot read candidate kernel BTF')
        raw = ctypes.string_at(pointer, size.value)
        self.base_sha256 = hashlib.sha256(raw).hexdigest()
        if kernel_image is not None and raw not in kernel_image.read_bytes():
            self.close()
            raise ValueError('vmlinux BTF is absent from the candidate kernel Image')

    def require(self, value, label):
        error = self.lib.libbpf_get_error(value)
        if error or not value:
            raise ValueError(f'Invalid BTF for {label}: errno {error or ctypes.get_errno()}')
        return value

    def check(self, path):
        data = sections(path)
        if '.BTF' not in data:
            return False
        embedded, module = None, None
        try:
            base = self.base
            if '.BTF.base' in data:
                raw = data['.BTF.base']
                embedded = self.require(self.lib.btf__new(raw, len(raw)), str(path) + ' .BTF.base')
                base = embedded
            raw = data['.BTF']
            module = self.require(self.lib.btf__new_split(raw, len(raw), base), path)
            if embedded:
                error = self.lib.btf__relocate(module, self.base)
                if error:
                    raise ValueError(f'BTF base relocation failed for {path}: errno {error}')
            return True
        finally:
            if module:
                self.lib.btf__free(module)
            if embedded:
                self.lib.btf__free(embedded)

    def close(self):
        if self.base:
            self.lib.btf__free(self.base)
            self.base = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vmlinux', type=Path, required=True)
    parser.add_argument('--kernel-image', type=Path)
    parser.add_argument('--module-dir', type=Path)
    parser.add_argument('modules', type=Path, nargs='*')
    args = parser.parse_args()
    paths = list(args.modules)
    if args.module_dir:
        paths += sorted(args.module_dir.rglob('*.ko*'))
    paths = [p for p in paths if p.is_file() and (p.name.endswith('.ko') or p.suffix in ('.xz', '.gz', '.zst'))]
    if not paths:
        parser.error('No module files selected')
    checker = None
    try:
        checker = Checker(args.vmlinux, args.kernel_image)
        typed = sum(checker.check(path) for path in paths)
        print(json.dumps({'modules_checked': len(paths), 'modules_with_btf': typed,
                          'kernel_btf_sha256': checker.base_sha256}))
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        if checker:
            checker.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
