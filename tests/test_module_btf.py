"""Reject a kernel relink's stale split BTF even when symbol CRCs are unchanged."""
import ctypes
import gzip
import importlib.util
import lzma
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('module_btf', ROOT/'scripts/verify-module-btf.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def btf(types, strings):
    return struct.pack('<HBBIIIII', 0xeb9f, 1, 0, 24, 0, len(types), len(types), len(strings)) + types + strings


def record(name, kind, value, linkage=0):
    return struct.pack('<III', name, kind << 24 | linkage, value)


class ModuleBtfTests(unittest.TestCase):
    def setUp(self):
        try:
            ctypes.CDLL('libbpf.so.1')
        except OSError:
            self.skipTest('libbpf is required for offline module BTF validation')
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.empty = self.root/'empty.o'
        subprocess.run(['cc', '-x', 'c', '-c', '-o', str(self.empty), '-'],
                       input=b'int fixture;\n', check=True, capture_output=True)
        integer = record(1, 1, 4) + struct.pack('<I', 1 << 24 | 32)
        proto = record(0, 13, 1)
        strings = b'\0int\0'
        self.old_raw = btf(integer + proto, strings)
        self.new_raw = btf(integer + record(0, 2, 1) + proto, strings)
        module = btf(record(len(strings)+1, 12, 2, 1), b'\0demo\0')
        self.old = self.elf('old', {'.BTF': self.old_raw})
        self.new = self.elf('new', {'.BTF': self.new_raw})
        self.module = self.elf('module', {'.BTF': module})

    def elf(self, name, data):
        output = self.root/(name+'.ko')
        command = ['objcopy']
        for section, raw in data.items():
            path = self.root/(name+section)
            path.write_bytes(raw)
            command += ['--add-section', section+'='+str(path)]
        subprocess.run(command+[str(self.empty), str(output)], check=True, capture_output=True)
        return output

    def checker(self, base, image=None):
        checker = verify.Checker(base, image)
        self.addCleanup(checker.close)
        return checker

    def test_matching_native_split_btf_passes(self):
        self.assertTrue(self.checker(self.old).check(self.module))

    def test_relinked_base_rejects_unchanged_module(self):
        with self.assertRaisesRegex(ValueError, 'Invalid BTF'):
            self.checker(self.new).check(self.module)

    def test_kernel_image_must_contain_the_same_base_btf(self):
        image = self.root/'Image'
        image.write_bytes(b'fixture'+self.old_raw)
        self.checker(self.old, image)
        with self.assertRaisesRegex(ValueError, 'absent'):
            self.checker(self.new, image)

    def test_distilled_base_relocates_after_base_type_ids_change(self):
        checker = self.checker(self.old)
        raw = verify.sections(self.module)['.BTF']
        source = checker.require(checker.lib.btf__new_split(raw, len(raw), checker.base), self.module)
        base, split = ctypes.c_void_p(), ctypes.c_void_p()
        distill = checker.lib.btf__distill_base
        distill.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        distill.restype = ctypes.c_int
        try:
            self.assertEqual(distill(source, ctypes.byref(base), ctypes.byref(split)), 0)
            sections = {}
            for name, pointer in [('.BTF', split), ('.BTF.base', base)]:
                size = ctypes.c_uint32()
                pointer = checker.lib.btf__raw_data(pointer, ctypes.byref(size))
                sections[name] = ctypes.string_at(pointer, size.value)
            module = self.elf('relocatable', sections)
            self.assertTrue(self.checker(self.new).check(module))
        finally:
            for pointer in (source, split, base):
                if pointer:
                    checker.lib.btf__free(pointer)

    def test_compressed_modules_keep_the_same_validation(self):
        checker = self.checker(self.old)
        for suffix, compress in [('.xz', lzma.compress), ('.gz', gzip.compress)]:
            path = self.module.with_suffix('.ko'+suffix)
            path.write_bytes(compress(self.module.read_bytes()))
            self.assertTrue(checker.check(path))

    def test_absent_btf_is_reported_without_loading_any_module(self):
        self.assertFalse(self.checker(self.old).check(self.empty))

    def test_truncated_elf_fails_closed(self):
        self.module.write_bytes(b'\x7fELF\x02\x01')
        with self.assertRaises((ValueError, struct.error)):
            self.checker(self.old).check(self.module)


if __name__ == '__main__':
    unittest.main()
