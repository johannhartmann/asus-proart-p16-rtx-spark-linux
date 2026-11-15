"""Ensure debug candidates cannot silently lose instrumentation or alter defaults."""
import importlib.util
import hashlib
import json
import re
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kernel_candidate', ROOT/'scripts/prepare-kernel-candidate.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class KernelDebugTests(unittest.TestCase):
    def test_module_builder_waits_for_finalized_package_manifest(self):
        spec = importlib.util.spec_from_file_location(
            'module_candidate', ROOT/'scripts/prepare-platform-candidate.py')
        modules = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modules)
        with tempfile.TemporaryDirectory() as tmp:
            out, parent = Path(tmp)/'modules', Path(tmp)/'kernel'
            out.mkdir()
            parent.mkdir()
            candidate.save(parent/'job.json', {'status': 'complete', 'exit_code': 0})
            candidate.save(parent/'manifest.json', {})
            with patch.object(modules.os, 'geteuid', return_value=1000), \
                    patch.object(modules, 'verify_sources') as verify:
                with self.assertRaisesRegex(RuntimeError, 'package manifest is not finalized'):
                    modules.build(out, {'kernel_candidate': str(parent)})
            verify.assert_not_called()
            self.assertFalse((out/'job.json').exists())

    def test_complete_status_follows_package_manifest_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            job = {'status': 'running', 'log': 'build.log'}
            candidate.save(out/'job.json', job)
            manifest = {'attempts': []}

            def record(output, state, completed):
                self.assertEqual(json.loads((out/'job.json').read_text())['status'], 'running')
                self.assertEqual(completed['status'], 'complete')
                state['packages'] = {'kernel.pkg.tar.zst': 'verified'}
                candidate.save(output/'manifest.json', state)

            with patch.object(candidate, 'verify_inputs'), \
                    patch.object(candidate, 'record_packages', side_effect=record):
                candidate.finish_build(out, manifest, job, 0)
            self.assertEqual(json.loads((out/'job.json').read_text())['status'], 'complete')
            self.assertIn('packages', json.loads((out/'manifest.json').read_text()))

    def test_package_validation_failure_cannot_publish_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            job = {'status': 'running', 'log': 'build.log'}
            candidate.save(out/'job.json', job)
            with patch.object(candidate, 'verify_inputs'), \
                    patch.object(candidate, 'record_packages', side_effect=RuntimeError('bad package')):
                with self.assertRaisesRegex(RuntimeError, 'bad package'):
                    candidate.finish_build(out, {'attempts': []}, job, 0)
            saved = json.loads((out/'job.json').read_text())
            self.assertEqual((saved['status'], saved['exit_code']), ('failed', 1))
            self.assertEqual(saved['validation_error'], 'bad package')

    def test_failed_build_does_not_record_successful_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            job = {'status': 'running', 'log': 'build.log'}
            with patch.object(candidate, 'verify_inputs'), \
                    patch.object(candidate, 'record_packages') as record:
                candidate.finish_build(out, {'attempts': []}, job, 2)
            record.assert_not_called()
            self.assertEqual(json.loads((out/'job.json').read_text())['status'], 'failed')
            self.assertEqual(json.loads((out/'manifest.json').read_text())['attempts'][0]['exit_code'], 2)

    def test_separately_installed_candidate_keeps_kernel_and_headers_together(self):
        raw = (ROOT/'kernel/PKGBUILD').read_bytes()
        self.assertEqual(candidate.package_recipe(raw, 'linux-p16-platform'), raw)
        numbered = candidate.package_recipe(raw, 'linux-p16-platform-32').decode()
        self.assertIn('pkgbase=linux-p16-platform-32\n', numbered)
        self.assertIn('_kernel=$pkgbase', numbered)
        for invalid in ('linux', 'linux-p16-platform-0', 'linux-p16-platform-32;id', '../kernel'):
            with self.assertRaisesRegex(RuntimeError, 'Invalid candidate package base'):
                candidate.package_recipe(raw, invalid)

    def test_default_configuration_stays_identical(self):
        raw = (ROOT/'kernel/config.aarch64').read_bytes()
        self.assertEqual(candidate.set_config(raw, candidate.debug_settings('none')), raw)

    def test_sanitizers_are_separate_and_both_require_lockdep_and_dma_debug(self):
        raw = (ROOT/'kernel/config.aarch64').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'.config'
            for profile, enabled, disabled in (('kasan', 'KASAN', 'KCSAN'),
                                                ('kcsan', 'KCSAN', 'KASAN')):
                settings = candidate.debug_settings(profile)
                path.write_bytes(candidate.set_config(raw, settings))
                candidate.verify_debug_config(path, settings)
                self.assertEqual(settings[enabled], 'y')
                self.assertEqual(settings[disabled], 'n')
                self.assertEqual(settings['PROVE_LOCKING'], 'y')
                self.assertEqual(settings['DMA_API_DEBUG'], 'y')
                self.assertEqual(settings['KUNIT'], 'y')
                for name, value in {
                    'LOCKDEP_SMALL': 'n', 'LOCKDEP_BITS': '18',
                    'LOCKDEP_CHAINS_BITS': '19', 'LOCKDEP_STACK_TRACE_BITS': '23',
                    'LOCKDEP_STACK_TRACE_HASH_BITS': '18',
                    'LOCKDEP_CIRCULAR_QUEUE_BITS': '14',
                }.items():
                    self.assertEqual(settings[name], value)
                # Model Kconfig dropping an unsupported dependency: packaging must fail.
                path.write_text(path.read_text().replace('CONFIG_PROVE_LOCKING=y',
                                                         '# CONFIG_PROVE_LOCKING is not set'))
                with self.assertRaisesRegex(RuntimeError, 'CONFIG_PROVE_LOCKING'):
                    candidate.verify_debug_config(path, settings)

    def test_debug_config_is_repinned_without_weakening_source_validation(self):
        inputs = {name: (ROOT/name).read_bytes() for name in
                  ('kernel/config.aarch64', 'kernel/PKGBUILD')}
        original = inputs['kernel/PKGBUILD']
        candidate.configure_debug_inputs(inputs, candidate.debug_settings('kasan'))
        self.assertNotEqual(inputs['kernel/PKGBUILD'], original)
        for algorithm, field in (('sha256', 'sha256sums_aarch64'),
                                 ('blake2b', 'b2sums_aarch64')):
            expected = re.search(
                field+r"=\('([a-f0-9]+)'\)", inputs['kernel/PKGBUILD'].decode())
            self.assertEqual(expected.group(1), hashlib.new(algorithm, inputs['kernel/config.aarch64']).hexdigest())
        # A stale or edited original config must not silently become trusted.
        inputs['kernel/config.aarch64'] += b'\n# unexpected mutation\n'
        with self.assertRaisesRegex(RuntimeError, 'Original config checksum'):
            candidate.configure_debug_inputs(inputs, candidate.debug_settings('kcsan'))

    def test_version_is_set_after_patches_and_checked_before_build(self):
        # A vendor patch creates localversion.40-asus. Exercise actual prepare()
        # with modeled patch/make edges to catch version ordering regressions.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tree = root/'linux-7.2.8'
            tree.mkdir()
            tools = root/'tools'
            tools.mkdir()
            (root/'config.aarch64').write_text('CONFIG_LOCALVERSION=""\n')
            (tree/'scripts').mkdir()
            scripts = {
                tree/'scripts/config': '#!/bin/sh\nexit 0\n',
                tools/'patch': '#!/bin/sh\ncat >/dev/null\nprintf "%s\\n" -asus > localversion.40-asus\n',
                tools/'make': '#!/usr/bin/python3\nimport pathlib,sys\nif "kernelrelease" in sys.argv:\n print("7.2.8"+"".join(p.read_text().strip() for p in sorted(pathlib.Path.cwd().glob("localversion.*"))))\n',
            }
            for path, body in scripts.items():
                path.write_text(body)
                path.chmod(0o755)
            shell = r'''
set -e
source "$1"
for name in "${source[@]}"; do
 name=${name%%::*};name=${name##*/};name=${name%.zst}
 [[ $name != *.patch ]] || touch "$2/$name"
done
srcdir=$2
cd "$srcdir"
prepare
'''
            import os
            env = dict(os.environ, P16_KERNEL_RELEASE='29', CARCH='aarch64',
                       PATH=str(tools)+':'+os.environ['PATH'])
            subprocess.run(['bash', '-c', shell, 'test', str(ROOT/'kernel/PKGBUILD'), str(root)],
                           env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.assertEqual((tree/'version').read_text().strip(), '7.2.8-29-rtx-spark-npu')
            self.assertFalse((tree/'localversion.40-asus').exists())

    def test_staged_vendor_helpers_remain_executable(self):
        spec = importlib.util.spec_from_file_location(
            'platform_candidate', ROOT/'scripts/prepare-platform-candidate.py')
        platform = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(platform)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'pahole.sh'
            source.write_text('#!/bin/sh\nexit 0\n')
            source.chmod(0o755)
            output = root/'candidate'
            target = output/'nvidia/kernel-open/pahole.sh'
            records = {}
            platform.copy_input(source, target, records, output)
            subprocess.run([str(target)], check=True)
            self.assertEqual(records[str(target.relative_to(output))],
                             hashlib.sha256(source.read_bytes()).hexdigest())
