"""Reject corrupt firmware inputs and malformed ACPI before extraction/install."""
import hashlib
import importlib.util
import importlib.machinery
import json
from pathlib import Path
import struct
import subprocess
import ast
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(path)))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


inventory = module("platform_inventory", "platform-inventory.py")
extractor = module("platform_extractor", "extract-platform-drivers.py")
dsp = module("dsp_firmware", "prepare-dsp-firmware.py")
live = module("platform_live", "validate-platform-live.py")
dsp_live = module("dsp_live", "validate-dsp-live.py")
provider_live = module("provider_live", "validate-sroot-provider.py")
dsp_boot = module("dsp_boot", "validate-dsp-boot.py")
platform_audit = module("platform_audit", "verify-platform-install.py")


class DSPSignedContainerTests(unittest.TestCase):
    @staticmethod
    def cbor(value):
        def head(major, size):
            if size < 24:
                return bytes([(major << 5) | size])
            for additional, width in ((24, 1), (25, 2), (26, 4), (27, 8)):
                if size < 1 << (width * 8):
                    return bytes([(major << 5) | additional]) + size.to_bytes(width, "big")
            raise ValueError("Fixture integer too large")
        encode = DSPSignedContainerTests.cbor
        if isinstance(value, int):
            return head(0 if value >= 0 else 1, value if value >= 0 else -1 - value)
        if isinstance(value, bytes):
            return head(2, len(value)) + value
        if isinstance(value, list):
            return head(4, len(value)) + b"".join(encode(v) for v in value)
        if isinstance(value, dict):
            return head(5, len(value)) + b"".join(encode(k) + encode(v) for k, v in value.items())
        if isinstance(value, tuple):
            return head(6, value[0]) + encode(value[1])
        raise TypeError(value)

    def image(self):
        # Synthetic hashes and fake signatures exercise parsing only; they are
        # deliberately not accepted as pinned OEM firmware by prepare().
        native = bytearray(208)
        struct.pack_into("<III", native, 0, 1, 6, 0xefbeadde)
        struct.pack_into("<I", native, 204, 0xefbeadde)
        offset = 0
        for i, section in enumerate((0, 0x1000, 0x2100, 0x2200, 0x2300, 0x2000)):
            header, payload = (0, 208) if i == 0 else (208, 4)
            struct.pack_into("<8I", native, 12 + 32 * i,
                             0xefbeadde, 0xc0304, section, offset, header, payload, 0, 0)
            offset += header + payload
        native.extend(bytes(offset - len(native)))
        digests = []
        for i in range(6):
            _, _, _, offset, header, payload, _, _ = struct.unpack_from("<8I", native, 12 + 32 * i)
            digests.append([-43, hashlib.sha384(native[offset:offset + header + payload]).digest()])
        bodies = []
        for identity, protected_size, signature_size in ((1, 133, 96), (2, 423, 384)):
            metadata = {-1277952: {0: 1, 1: identity, 2: 1010580826,
                                  3: 0, 4: 0, 5: [0] * 6},
                        -1294334: digests, -1310719: 208}
            bodies.append([[(98, [b"", {}, self.cbor(metadata),
                                  [[bytes(protected_size), {}, bytes(signature_size)]]])]])
        prefix = self.cbor(bodies + [bytes(11)])
        self.assertEqual(len(prefix), 1805)
        return b"\x59\x07\x0d" + prefix + native

    def test_signed_container_hashes_are_not_reported_as_authentication(self):
        result = dsp.inspect_image(self.image(), 0xc0304)
        self.assertEqual(len(result["sections"]), 6)
        self.assertTrue(result["section_digests_verified"])
        self.assertFalse(result["signatures_authenticated"])

    def test_corruption_truncation_wrong_core_and_trailing_data_are_rejected(self):
        image = self.image()
        corrupt = bytearray(image)
        corrupt[-1] ^= 1
        for data, image_id in ((image[:-1], 0xc0304), (image + b"x", 0xc0304),
                               (corrupt, 0xc0304), (image, 0xc0305)):
            with self.subTest(size=len(data), image_id=image_id):
                with self.assertRaises(ValueError):
                    dsp.inspect_image(data, image_id)

    def test_cbor_limits_duplicates_and_indefinite_lengths_are_rejected(self):
        for data in (b"\x9f", b"\x5b" + b"\xff" * 8,
                     b"\x81" * 14 + b"\x00", b"\xa2\x00\x01\x00\x02"):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    dsp.CBOR(data).complete()


class ProviderBootServiceTests(unittest.TestCase):
    def layout(self, root, instance="00"):
        controls = []
        for index, hid in enumerate(("NVDA200A", "NVDA8600")):
            name, supplier = f"{hid}:{instance}", f"iommu-controller-{index}"
            device = root / "bus/platform/devices" / name
            device.mkdir(parents=True)
            (device / "firmware_node").mkdir()
            (device / "firmware_node/hid").write_text(hid + "\n")
            iommu = root / supplier
            iommu.mkdir()
            (device / "iommu").symlink_to(iommu)
            group = root / "kernel/iommu_groups" / str(index)
            (group / "devices").mkdir(parents=True)
            (group / "devices" / name).symlink_to(device)
            (device / "iommu_group").symlink_to(group)
            (group / "type").write_text("identity\n")
            controls.append(group / "type")
        return controls

    def test_dma_domains_are_selected_only_after_both_groups_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls = self.layout(root)
            extra = controls[1].parent / "devices/another-device"
            extra.symlink_to(root / "another-device")
            result = self.run_helper(root, "--prepare")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("shared", result.stderr)
            self.assertTrue(all(p.read_text().strip() == "identity" for p in controls))
            extra.unlink()
            result = self.run_helper(root, "--prepare")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(all(p.read_text().strip() == "DMA" for p in controls))

    def run_helper(self, root, mode):
        # Replace literal sysfs paths in a test-only copy; the installed helper
        # deliberately has no environment override for hardware access.
        script = (ROOT / "platform/dsp/provider/n1x-platform-npu-start").read_text()
        script = script.replace("/sys/", str(root) + "/")
        return subprocess.run(["bash", "-c", script, "test-helper", mode], text=True, capture_output=True)

    def test_host_check_has_no_kernel_version_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.layout(root, instance="17")
            result = self.run_helper(root, "--check-host")
            self.assertEqual(result.returncode, 0, result.stderr)
        script = (ROOT / "platform/dsp/provider/n1x-platform-npu-start").read_text()
        self.assertNotIn("uname", script)
        self.assertNotIn("python", script)
        self.assertNotIn("dmi", script)
        self.assertNotIn("smmu3.0x", script)
        self.assertNotIn("NVDA200A:00", script)

    def test_other_instance_names_work_without_dmi_and_ambiguous_devices_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls = self.layout(root, instance="42")
            self.assertEqual(self.run_helper(root, "--prepare").returncode, 0)
            self.assertTrue(all(p.read_text().strip() == "DMA" for p in controls))
            duplicate = root / "bus/platform/devices/NVDA200A:99/firmware_node"
            duplicate.mkdir(parents=True)
            (duplicate / "hid").write_text("NVDA200A\n")
            result = self.run_helper(root, "--check-host")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Multiple", result.stderr)

    def test_partially_bound_endpoints_prevent_domain_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls = self.layout(root)
            driver = root / "bus/platform/devices/NVDA200A:00/driver"
            driver.mkdir()
            result = self.run_helper(root, "--prepare")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Partially bound", result.stderr)
            self.assertTrue(all(p.read_text().strip() == "identity" for p in controls))


class ManagedKernelHookTests(unittest.TestCase):
    def test_new_kernel_and_late_firmware_targets_preserve_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            modules = root / "modules"
            packages = ("linux-omarchy", "linux-p16-asus-23", "linux-rtx-spark-npu", "linux-p16-platform-25")
            for package in packages:
                target = modules / package
                target.mkdir(parents=True)
                (target / "pkgbase").write_text(package)
            menu = root / "limine.conf"
            menu.write_text("".join("comment: kernel-id=" + p + " \n" for p in packages[:-1]))
            commands = root / "bin"
            commands.mkdir()
            pacman = commands / "pacman"
            pacman.write_text('#!/usr/bin/bash\nif [[ $1 == -Qqo ]]; then cat "${2%/*}/pkgbase"; fi\n')
            pacman.chmod(0o755)
            firmware = root / "firmware/nvidia"
            firmware.mkdir(parents=True)
            script = (ROOT / "scripts/p16-mkinitcpio-managed").read_text()
            script = script.replace("[[ $EUID == 0 ]]", "true")
            script = script.replace("PATH=/usr/bin:/bin", "PATH=" + str(commands) + ":/usr/bin:/bin")
            script = script.replace("/boot/limine.conf", str(menu)).replace("/usr/lib/modules/", str(modules) + "/")
            for targets in (str(firmware) + "\nusr/lib/firmware/nvidia/n1x/sroot-v0.bin\n",
                            str(modules / packages[-1] / "modules.builtin") + "\n"):
                # Keep target matching realistic; only the backing sysfs-like
                # file paths and command lookup differ in this isolated copy.
                if "modules.builtin" in targets:
                    targets = targets.replace(str(modules) + "/", "usr/lib/modules/")
                result = subprocess.run(["bash", "-c", script, "test", "--plan"], input=targets, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "Rebuilding managed Limine kernels: linux-p16-platform-25")
            (modules / packages[-1]).rename(modules / "linux-p16-platform")
            (modules / "linux-p16-platform/pkgbase").write_text("linux-p16-platform")
            result = subprocess.run(["bash", "-c", script, "test", "--plan"],
                                    input="usr/lib/firmware/nvidia/n1x/sroot-v0.bin\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "Rebuilding managed Limine kernels: linux-p16-platform")


class ACPICapabilityTests(unittest.TestCase):
    def test_only_strong_target_allocator_enables_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "future-kernel/build"
            target.mkdir(parents=True)
            script = (ROOT / "config/zz-p16-hardware-fixes.conf").read_text()
            script = script.replace("/usr/lib/modules/", str(root) + "/")
            for symbol, expected in (("W", "0"), ("T", "1")):
                (target / "System.map").write_text("0000000000000000 " + symbol + " arch_alloc_acpi_tables\n")
                result = subprocess.check_output(["bash", "-c", "KERNELVERSION=future-kernel; HOOKS=(); MODULES=(); " + script + '\necho "${#HOOKS[@]}"'], text=True)
                self.assertEqual(result.strip(), expected)


class DSPBootTrialTests(unittest.TestCase):
    def test_trial_requires_v2_from_the_shared_provider(self):
        dsp_boot.check_loader_api('0000000000000000 T n1x_sroot_client_ops_v4 [n1x_npu_bootstrap]\n')
        for symbols in (
                '0000000000000000 T n1x_sroot_upload_dsp_v1 [n1x_npu_bootstrap]\n',
                '0000000000000000 T n1x_sroot_client_ops_v4 [other_driver]\n',
                '0000000000000000 T n1x_sroot_client_ops_v4\n',
                '0000000000000000 T n1x_sroot_client_ops_v40 [n1x_npu_bootstrap]\n'):
            with self.assertRaisesRegex(RuntimeError, 'loader ABI v4'):
                dsp_boot.check_loader_api(symbols)

    def test_ready_without_staging_release_cannot_qualify_boot(self):
        valid = dict(image='0xc0303', published='1', loader_published='1', loader_accepted='1',
                     loader_staging_released='1', ready='1', error='0', power_error='0')
        dsp_boot.check_boot_result(valid, 0xc0303)
        for name in valid:
            missing = valid.copy()
            del missing[name]
            with self.assertRaises(RuntimeError):
                dsp_boot.check_boot_result(missing, 0xc0303)
            wrong = valid.copy()
            wrong[name] = 'bad' if name == 'image' else ('0' if valid[name] == '1' else '1')
            with self.assertRaises(RuntimeError):
                dsp_boot.check_boot_result(wrong, 0xc0303)
        with self.assertRaises(RuntimeError):
            dsp_boot.check_boot_result(valid, 0xc0304)

    def test_trial_manifest_requires_fresh_boot_and_matching_driver_set(self):
        previous = 'db4397f4-646b-4b7d-9831-567db6218147'
        fresh = '70000000-0000-4000-8000-000000000001'
        release = '7.2.8-25-omarchy-p16-asus-npu'
        manifest = dict(kernel_release=release, source_boot_id=previous, loader_abi=4,
                        drivers={name: {'srcversion': value} for name, value in
                                 (('provider', 'P'), ('dsp', 'D'), ('afe', 'A'))})
        dsp_boot.check_trial_manifest(manifest, release, fresh, 'P', 'D', 'A')
        for actual in ((release, previous, 'P', 'D', 'A'),
                       ('other-kernel', fresh, 'P', 'D', 'A'),
                       (release, fresh, 'wrong', 'D', 'A'),
                       (release, fresh, 'P', 'wrong', 'A'),
                       (release, fresh, 'P', 'D', 'wrong')):
            with self.assertRaises(RuntimeError):
                dsp_boot.check_trial_manifest(manifest, *actual)
        for key, value in (('loader_abi', 1), ('source_boot_id', ''), ('source_boot_id', '-' * 36)):
            invalid = manifest | {key: value}
            with self.assertRaises(RuntimeError):
                dsp_boot.check_trial_manifest(invalid, release, fresh, 'P', 'D', 'A')

    def test_firmware_publish_preserves_existing_and_conflicting_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "firmware.bin"
            self.assertTrue(dsp_boot.publish_file(target, b"verified firmware"))
            self.assertFalse(dsp_boot.publish_file(target, b"verified firmware"))
            with self.assertRaisesRegex(RuntimeError, "Preserving conflicting"):
                dsp_boot.publish_file(target, b"different firmware")
            self.assertEqual(target.read_bytes(), b"verified firmware")
            link = Path(directory) / "link.bin"
            link.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "Preserving conflicting"):
                dsp_boot.publish_file(link, b"verified firmware")
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["firmware.bin", "link.bin"])

    def test_failed_atomic_publish_cleans_up_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "firmware.bin"
            with patch.object(dsp_boot.os, "link", side_effect=FileExistsError("race")):
                with self.assertRaises(FileExistsError):
                    dsp_boot.publish_file(target, b"verified firmware")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_child_boot_writer_sends_the_exact_six_byte_command(self):
        tree = ast.parse((ROOT / "scripts/validate-dsp-boot.py").read_text())
        writers = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and
                   isinstance(n.value, str) and n.value.startswith("import os,sys;f=os.open")]
        self.assertEqual(len(writers), 1)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "control"
            target.touch()
            subprocess.run(["python", "-c", writers[0], str(target)], check=True)
            self.assertEqual(target.read_bytes(), b"start\n")


class ProviderTrialTests(unittest.TestCase):
    def state(self, stopped=False):
        return {"status": dict.fromkeys(("dla_bound", "sroot_bound", "idle_observed", "ping_verified",
                "region5_registered", "config_valid", "config_apply_accepted", "lpwr_accepted", "task_verified"), "1") |
                {"queue_poisoned": "0", "error": "0"},
                "hfrp_status": {"error": "0", "power_accepted": "1"},
                "shutdown_status": {"attempted": "1" if stopped else "0", "error": "0",
                    "hardware_off": "1" if stopped else "0", "released": "1" if stopped else "0",
                    "hfrp_held": "0" if stopped else "1", "upload_held": "0" if stopped else "1"},
                "module_refcnt": "0", "info": {"abi_version": 2, "capabilities": 8,
                    "retained_jobs": 0, "retained_bytes": 0}}

    def test_busy_unhealthy_or_previously_stopped_driver_is_not_changed(self):
        for area, key, value in (("info", "retained_jobs", 1), ("info", "retained_bytes", 1),
                                 ("info", "capabilities", 0), ("info", "abi_version", 1),
                                 ("status", "queue_poisoned", "1"), ("status", "task_verified", "0"),
                                 ("hfrp_status", "error", "-5"), ("shutdown_status", "attempted", "1")):
            with self.subTest(key=key):
                state = self.state()
                state[area][key] = value
                with patch.object(provider_live, "snapshot", return_value=state), \
                     patch.object(provider_live, "trigger_stop") as stop, \
                     patch.object(provider_live, "run") as run:
                    with self.assertRaises(RuntimeError):
                        provider_live.checked_stop_and_unload({})
                    stop.assert_not_called()
                    run.assert_not_called()

    def test_unconfirmed_stop_or_retained_references_prevent_removal(self):
        for key, value in (("hardware_off", "0"), ("released", "0"), ("error", "-5"),
                           ("hfrp_held", "1"), ("upload_held", "1"), ("module_refcnt", "1")):
            with self.subTest(key=key):
                after = self.state(stopped=True)
                if key == "module_refcnt":
                    after[key] = value
                else:
                    after["shutdown_status"][key] = value
                with patch.object(provider_live, "snapshot", side_effect=[self.state(), after]), \
                     patch.object(provider_live, "trigger_stop") as stop, \
                     patch.object(provider_live, "run") as run:
                    with self.assertRaises(RuntimeError):
                        provider_live.checked_stop_and_unload({})
                    stop.assert_called_once()
                    run.assert_not_called()

    def test_confirmed_hardware_stop_reaches_only_normal_removal(self):
        with patch.object(provider_live, "snapshot", side_effect=[self.state(), self.state(stopped=True)]), \
             patch.object(provider_live, "trigger_stop") as stop, \
             patch.object(provider_live, "run", side_effect=RuntimeError("normal removal boundary")) as run:
            with self.assertRaisesRegex(RuntimeError, "normal removal boundary"):
                provider_live.checked_stop_and_unload({})
            stop.assert_called_once()
            run.assert_called_once_with(["rmmod", "n1x_npu_bootstrap"])


class DSPProbeTrialTests(unittest.TestCase):
    def test_failed_insert_and_failed_probe_restore_original_driver(self):
        for failed_insert in (True, False):
            with self.subTest(failed_insert=failed_insert), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "test.ko").write_bytes(b"test module fixture")
                modules, drivers = root / "modules", root / "drivers"
                original = modules / "snd_sof_mt8901"
                original.mkdir(parents=True)
                (original / "refcnt").write_text("0")
                driver = drivers / dsp_live.ORIGINAL
                driver.mkdir(parents=True)
                for name in dsp_live.DEVICES:
                    (driver / name).symlink_to(root / name)
                calls = []

                def run(args):
                    calls.append(args[:2])
                    if args[0] == "insmod":
                        if failed_insert:
                            raise RuntimeError("insert failed")
                        parameter = modules / "n1x_adsp/parameters/enable_boot"
                        parameter.parent.mkdir(parents=True)
                        parameter.write_text("N")
                    return ""

                waits = [None, {"restored": True}] if failed_insert else \
                        [None, RuntimeError("probe failed"), {"restored": True}]
                report = {}
                with patch.object(dsp_live, "load_script", return_value=live), \
                     patch.object(live, "check_target"), patch.object(live, "check_module", return_value=root / "test.ko"), \
                     patch.object(dsp_live, "wait_suspended", side_effect=waits), \
                     patch.object(dsp_live, "run", side_effect=run):
                    with self.assertRaisesRegex(RuntimeError, "insert failed|probe failed"):
                        dsp_live.probe_trial(root / "test.ko", report, modules, drivers)
                self.assertEqual(calls[-1], ["modprobe", "snd_sof_mt8901"])
                self.assertEqual(["rmmod", "n1x_adsp"] in calls, not failed_insert)
                self.assertEqual(report["restored"], {"restored": True})


class LiveTrialTests(unittest.TestCase):
    def test_unvalidated_bios_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            dmi = Path(temporary)
            (dmi / "product_name").write_text("ProArt P16 H7607BA\n")
            (dmi / "bios_version").write_text("H7607BA.300\n")
            live.check_target(dmi)
            (dmi / "bios_version").write_text("H7607BA.301\n")
            with self.assertRaisesRegex(RuntimeError, "Unvalidated bios_version"):
                live.check_target(dmi)

    def test_shared_spi_driver_is_rejected_before_unload(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "spi-MSFW1111:00").symlink_to(directory / "target")
            live.check_sensor_bindings(directory)
            (directory / "spi-another-device").symlink_to(directory / "another")
            check = live.check_sensor_bindings
            with patch.object(live, "check_sensor_bindings",
                              side_effect=lambda: check(directory)), \
                 patch.object(live, "command") as run:
                with self.assertRaisesRegex(RuntimeError, "refusing to unload shared"):
                    with live.sensor_trial(Path("core.ko"), Path("acpi.ko")):
                        self.fail("Trial must not start")
                run.assert_not_called()

    def sensor_context(self, run):
        self.enterContext(patch.object(live, "check_sensor_bindings"))
        self.enterContext(patch.object(live, "check_module", side_effect=lambda p: p))
        self.enterContext(patch.object(live, "command", side_effect=run))
        self.enterContext(patch.object(live.Path, "exists", return_value=True))
        return live.sensor_trial(Path("core.ko"), Path("acpi.ko"))

    def test_busy_core_restores_acpi_without_retrying_unload(self):
        calls = []

        def run(args):
            calls.append(args)
            if args == ["rmmod", "spi_hid"]:
                raise RuntimeError("core is busy")
            return ""

        with self.assertRaisesRegex(RuntimeError, "core is busy"):
            with self.sensor_context(run):
                self.fail("Trial must not start")
        self.assertEqual(calls[-1], ["modprobe", "spi_hid_acpi"])
        self.assertEqual(calls.count(["rmmod", "spi_hid"]), 1)
        self.assertFalse(any(call[0] == "insmod" for call in calls))

    def test_failed_acpi_insert_removes_trial_core_and_restores_packaged_driver(self):
        calls = []

        def run(args):
            calls.append(args)
            if args == ["insmod", Path("acpi.ko")]:
                raise RuntimeError("ACPI insert failed")
            return ""

        with self.assertRaisesRegex(RuntimeError, "ACPI insert failed"):
            with self.sensor_context(run):
                self.fail("Trial must not start")
        self.assertEqual(calls[-2:], [["rmmod", "spi_hid"], ["modprobe", "spi_hid_acpi"]])

    def test_failed_sample_unloads_both_trial_modules_and_restores_packaged_driver(self):
        calls = []

        def run(args):
            calls.append(args)
            return ""

        with self.assertRaisesRegex(RuntimeError, "sample failed"):
            with self.sensor_context(run):
                raise RuntimeError("sample failed")
        self.assertEqual(calls[-3:], [["rmmod", "spi_hid_acpi"], ["rmmod", "spi_hid"],
                                      ["modprobe", "spi_hid_acpi"]])

    def test_failed_pluton_discovery_unloads_trial_module(self):
        calls = []
        with patch.object(live, "check_module", side_effect=lambda p: p), \
             patch.object(live.Path, "exists", return_value=False), \
             patch.object(live, "command", side_effect=lambda args: calls.append(args)):
            with self.assertRaisesRegex(RuntimeError, "discovery failed"):
                with live.pluton_trial(Path("pluton.ko")):
                    raise RuntimeError("discovery failed")
        self.assertEqual(calls, [["insmod", Path("pluton.ko"), "enable_transport=1"],
                                 ["rmmod", "n1x_pluton"]])


class IIOInventoryTests(unittest.TestCase):
    def test_iio_bus_devices_are_found_without_reading_raw_channels_or_triggers(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for identifier, name in (("iio:device0", "human_presence"),
                                     ("iio:device1", "als"), ("trigger0", "ignore")):
                path = directory / identifier
                path.mkdir()
                (path / "name").write_text(name + "\n")
                # A raw read would block forever; inventory must only read
                # identification attributes and leave this FIFO unopened.
                import os
                os.mkfifo(path / "in_illuminance_raw")
            result = inventory.iio_devices(directory)
            self.assertEqual([x["id"] for x in result], ["iio:device0", "iio:device1"])
            self.assertEqual([x["name"] for x in result], ["human_presence", "als"])


class DSPBundleTests(unittest.TestCase):
    def bundle(self):
        return (struct.pack("<I", 2) + b"mt8901" + struct.pack("<I", 3) +
                b"mt8971" + struct.pack("<I", 5) + b"one" + b"other")

    def test_correct_soc_is_selected_without_modifying_signed_bytes(self):
        result = dsp.variants(self.bundle())
        self.assertEqual(result[b"mt8901"], (24, b"one"))
        self.assertEqual(result[b"mt8971"], (27, b"other"))

    def test_truncation_overflow_duplicate_soc_and_trailing_bytes_are_rejected(self):
        bad_size = bytearray(self.bundle())
        struct.pack_into("<I", bad_size, 10, 0xffffffff)
        duplicate = self.bundle().replace(b"mt8971", b"mt8901")
        for data in (b"", struct.pack("<I", 0), struct.pack("<I", 0xffffffff),
                     self.bundle()[:-1], self.bundle() + b"x", bad_size, duplicate):
            with self.subTest(data=bytes(data[:24])):
                with self.assertRaises(ValueError):
                    dsp.variants(data)


class ACPITableTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "TPM2"

    def table(self):
        data = bytearray(52)
        data[:4] = b"TPM2"
        struct.pack_into("<I", data, 4, len(data))
        struct.pack_into("<Q", data, 40, 0x12340000)
        struct.pack_into("<I", data, 48, 15)
        data[9] = -sum(data) % 256
        return data

    def test_ffa_tpm_is_distinguished_from_pluton(self):
        self.path.write_bytes(self.table())
        result = inventory.acpi_table(self.path)
        self.assertEqual(result["start_method"], 15)
        self.assertEqual(result["control_address"], "0x12340000")

    def test_truncated_and_corrupt_tables_are_rejected(self):
        for data in (b"TPM2", self.table()[:-1], self.table() + b"x"):
            with self.subTest(size=len(data)):
                self.path.write_bytes(data)
                with self.assertRaises(ValueError):
                    inventory.acpi_table(self.path)
        data = self.table()
        data[-1] ^= 1
        self.path.write_bytes(data)
        with self.assertRaises(ValueError):
            inventory.acpi_table(self.path)


class OEMExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.vendor = Path(self.temporary.name)
        self.recovery = self.vendor / "recovery.exe"
        self.recovery.write_bytes(b"verified container fixture")
        self.spec = {"sha256": hashlib.sha256(self.recovery.read_bytes()).hexdigest()}
        self.relative = "Windows/System32/DriverStore/FileRepository/test/firmware.bin"
        self.file = self.vendor / "platform-drivers" / self.relative
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(b"verified signed firmware fixture")
        self.lock = {"recovery": "recovery.exe", "files": [
            {"path": self.relative, "bytes": self.file.stat().st_size,
             "sha256": hashlib.sha256(self.file.read_bytes()).hexdigest()}]}

    def test_corrupt_recovery_never_invokes_an_extractor(self):
        self.recovery.write_bytes(b"wrong container")
        with patch.object(extractor.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                extractor.extract(self.vendor, self.lock, self.spec)
            run.assert_not_called()
        self.assertFalse((self.vendor / "platform-drivers.receipt.json").exists())

    def test_changed_firmware_is_preserved_and_not_certified(self):
        changed = b"a different OEM firmware revision"
        self.file.write_bytes(changed)
        with patch.object(extractor.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                extractor.extract(self.vendor, self.lock, self.spec)
            run.assert_not_called()
        self.assertEqual(self.file.read_bytes(), changed)
        self.assertFalse((self.vendor / "platform-drivers.receipt.json").exists())

    def test_verified_existing_inputs_need_no_extraction(self):
        with patch.object(extractor.subprocess, "run") as run:
            extractor.extract(self.vendor, self.lock, self.spec)
            run.assert_not_called()
        receipt = json.loads((self.vendor / "platform-drivers.receipt.json").read_text())
        self.assertFalse(receipt["windows_code_executed"])
        self.assertEqual(receipt["files"], self.lock["files"])

    def add_input(self):
        relative = 'Windows/System32/DriverStore/FileRepository/audio/audio.sys'
        data = b'additional verified driver fixture'
        self.lock['iso_path'] = 'recovery.iso'
        self.lock['files'].append({'path': relative, 'bytes': len(data),
                                   'sha256': hashlib.sha256(data).hexdigest()})
        return relative, data

    def extract_addition(self, relative, data):
        def capture(command, destination):
            destination.write_bytes(b'synthetic archive')

        def run(command, **kwargs):
            if command[0] == 'wimextract':
                self.assertIn('/' + str(Path(relative).parent), command)
                self.assertNotIn('/' + str(Path(self.relative).parent), command)
                dest = Path(next(arg.split('=', 1)[1] for arg in command
                                 if arg.startswith('--dest-dir=')))
                target = dest / relative
                target.parent.mkdir(parents=True)
                target.write_bytes(data)

        with patch.object(extractor, 'capture', side_effect=capture), \
             patch.object(extractor.subprocess, 'run', side_effect=run):
            return extractor.extract(self.vendor, self.lock, self.spec)

    def test_new_pinned_inputs_extend_an_existing_cache_without_replacing_files(self):
        relative, data = self.add_input()
        before = self.file.stat()
        result = self.extract_addition(relative, data)
        self.assertEqual((self.vendor / 'platform-drivers' / relative).read_bytes(), data)
        self.assertEqual(self.file.stat().st_ino, before.st_ino)
        self.assertEqual(self.file.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertFalse(result['windows_code_executed'])
        self.assertEqual(len(result['files']), 2)

    def test_bad_addition_is_rejected_before_publication(self):
        relative, data = self.add_input()
        before = self.file.read_bytes()
        with self.assertRaises(ValueError):
            self.extract_addition(relative, data + b'corrupt')
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse((self.vendor / 'platform-drivers' / relative).exists())
        self.assertFalse((self.vendor / 'platform-drivers.receipt.json').exists())

    def test_manifest_cannot_escape_the_extracted_tree(self):
        for relative in ("../outside", "/etc/passwd"):
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, "Unsafe manifest"):
                    extractor.validate_tree(self.vendor, [{"path": relative}])


if __name__ == "__main__":
    unittest.main()
