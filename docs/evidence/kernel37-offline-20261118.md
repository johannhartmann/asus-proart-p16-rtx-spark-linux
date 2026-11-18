# Kernel 37 Lockdep candidate: offline qualification

The exact ASUS ProArt P16 H7607BA candidate is `7.2.8-37-rtx-spark-npu`,
built from source commit `ca47e8af419fc6661ffb0aef20d1c7abe55665a8` with
KASAN and `CONFIG_PROVE_LOCKING=y`. Its final ARM64 Image SHA256 is
`ff8010b8ddce6f7319a823204069de019bff4ea614d5a617a1279992b5ff083c`.
The [machine-readable receipt](kernel37-offline-20261118.json) contains the
kernel, header and driver package hashes and each test's UART hash. The
[compressed UART logs](kernel37-offline-20261118/) preserve the guest output.

The candidate adds the MMU interval-notifier Lockdep correction already
reproduced against the original kernel36 Image. The two kernel37 MMU guest
cases passed with no warning and `debug_locks=1`: one inserts after notifier
pre-registration while holding `mmap_lock` for read, and the other exercises
the registration fallback without that lock. The earlier original-Image
positive control remains in
[the patch evidence](mmu-notifier-lockdep-20261118.md).

The matching external platform set was built from 4,081 hash-pinned inputs:
DSP, NPU provider, Pluton, SCP, ALS, sensor hub, hwmon, NVIDIA 615.78.08 and
development-only validation modules. All 8,507 built modules, including the
external set, passed split-BTF validation against the final `vmlinux`. The
13 production external modules were packaged using
[`package-platform-candidate.py`](../../scripts/package-platform-candidate.py);
the package was opened and each module's SHA256 checked against its build
manifest. The development-only probes are absent from that package.

Seven fresh AArch64 EFI/KVM cases passed against the exact final Image:

| Case | Result |
| --- | --- |
| MMU pre-registered and fallback | No warning; Lockdep remained enabled in both |
| 30-module/AFE/protocol boot | All modules loaded, AFE lifetime passed, no warning |
| PCIe/SDHCI hot removal | Removal passed with no warning |
| Guest `pm_test=platform` hot removal | Removal occurred after early resume; no noirq IRQ-thread wake or warning |
| NVIDIA UVM PM lock with two VA spaces | Four cycles and mutations, no warning, Lockdep remained enabled |
| NVIDIA UVM inverse-lock positive control | The intentional bad order produced the expected warning |

The host remained on kernel36 and NVIDIA 615.78.08 during these tests. No host
module was loaded, no host suspend was requested, and no boot file was written
by these builds or guests. These results qualify the offline candidate, not
native display, audio, camera, NVENC or physical suspend/resume. Those gates
require a complete staged boot and observed workloads on this P16.
