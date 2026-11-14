# Driver candidate qualification

The installed kernel and experimental DSP instances must remain available
until a matching candidate has passed its own fresh-boot tests. A build or
portable sanitizer test is not hardware qualification. Never force-unload a
published DSP or drop its DMA/provider references to obtain a passing test.

## Recorded baseline

On 2026-11-09, kernel `7.2.8-23-rtx-spark-npu` and the installed NPU module
(srcversion `AA4C27A61D0319E02A71961`) produced 16 correct cuDLA numerical
outputs, including five job-reuse submissions. The overlapping kernel-log
window contained no new relevant driver faults. All three DSPs reported
published firmware, accepted upload, readiness and error zero. The power
profile remained unchanged. These results qualify only that running baseline,
not the new context/client code.

## Native kernel31 verification, 13 November 2026

The repaired kernel31 bundle booted into Hyprland with zero module-BTF load
failures. Runtime vmlinux BTF matched the installed bundle. NVIDIA, the NPU,
all three DSPs and the internal SoundWire card initialized. DSP 0.1.25 / AFE
0.1.27 then passed all six bounded S16_LE/S24_LE playback, capture and duplex
tests, with nonzero capture and advancing firmware counters. Details and
qualification limits are recorded in [audio verification](audio.md#dsp-0125--afe-0127-native-pcm-verification)
and the [boot repair record](audio-boot-diagnostics.md#successful-native-boot-and-pcm-checks).

The debug kernel exhausted its lockdep chain-entry capacity before these tests.
This run therefore does not provide a clean lockdep qualification. No physical
suspend, DSP unload/reload, NPU numerical execution or complete physical audio
endpoint qualification was performed. The working kernel23 default is retained.

## Native kernel33 verification, 14 November 2026

Kernel33 booted with matching runtime BTF and maintained module srcversions.
An untraced six-case PCM baseline plus two complete DSP/AFE reload cycles each
passed six PCM cases and eight exact cuDLA outputs: 18 PCM rounds and 24
numerical outputs. Lockdep stayed enabled throughout, beyond the old dependency
limit, with no new kernel warnings during that matrix. The power profile was
unchanged; no livepatch, host suspend or additional reboot was used.

The first baseline playback had failed with `EBUSY` before this passing matrix.
A targeted traced request and the full subsequent untraced matrix did not
reproduce it. Its cause remains open; this is not an unconditional audio pass.
See the [complete native record](audio-boot-diagnostics.md#native-kernel33-results-on-14-november).
Real sleep, complete physical audio endpoints, KCSAN and sustained fault/recovery
qualification remain separate gates.

The later controlled device-only PM transaction returned with all three DSPs
ready and fresh resume counters, followed by passing PipeWire duplex, 18 traced
PCM cases and eight cuDLA outputs. It **failed overall qualification** because
NVIDIA's cross-callback PM writers triggered a circular Lockdep dependency and
disabled the validator. Those later functional checks therefore do not extend
the earlier clean Lockdep matrix. The candidate fix passes five hardware-free
EFI/KVM notifier/error cases; native NVIDIA and physical sleep checks remain
pending. See the [device-PM record](audio-boot-diagnostics.md#kernel33-device-only-pm-and-nvidia-lock-ordering).

## Reproducible candidates

The automatic ASoC DSP audio candidate requires NPU provider source
[`3ea7a7f80e40b24026da3c100c75ca18ed9672f2`](https://github.com/johannhartmann/n1x-npu-linux/commit/3ea7a7f80e40b24026da3c100c75ca18ed9672f2)
or an ABI-compatible merged revision with typed REINIT support. DSP 0.1.24
and the matching AFE must both use PCM client ABI 3. The AFE SRAM endpoint
remains ABI 2; it is a different interface. The
[interface matrix](platform-driver-status.md#current-dsp-interface-requirements)
separates all four contracts. Use that checkout for the sibling NPU tree.
First run the offline suites and pin the matching provider snapshot:

```sh
bash scripts/check-kernel-drivers.sh
make -C ../n1x-lab/npu check PYTHON=python3
python3 scripts/prepare-sroot-provider.py
```

Stage separate debug kernels. The commands below do not install packages,
change running drivers, write boot entries or alter the power profile:

```sh
python3 scripts/prepare-kernel-candidate.py \
  --output build/context-kasan --release 31 --debug kasan --jobs 8 --build
python3 scripts/prepare-platform-candidate.py \
  --kernel-candidate build/context-kasan --output build/context-kasan-modules \
  --hwmon-source build/spark_hwmon --nvidia-source /path/to/matching/nvidia-source \
  --jobs 8
```

Use a different output directory and release for `--debug kcsan` (for example,
release 32). KASAN and KCSAN are separate kernel configurations. Both enable
lockdep, DMA-API debugging and KUnit. Completed builds check that Kconfig kept
the required options. The module builder also produces the native protocol
KUnit module for debug candidates, the three matching DSP validation clients
and checks kernel/module identities. Build
manifests pin every input and output; do not substitute a module from another
kernel or a later checkout. Use the existing `--resume --build` path only for
the original unchanged candidate.

Install a completed, verified candidate as a separate boot option, preserving
the working default, recovery entry and menu timeout. A fresh boot is required
for a different kernel or an old pinned driver that lacks checked shutdown. The matching kernel33 bundle supports the tested native
DSP/AFE reload path; module replacement alone never changes already-loaded code.
Do not test a candidate against old already-loaded modules.

## Hardware sequence

1. Verify kernel release, module srcversions, boot ID and KASAN/KCSAN/lockdep/
   DMA-debug configuration against the manifests. Collect kernel logs from
   before the first test and pstore records after any unexpected reboot.
2. Run the native KUnit module. With DSP firmware unpublished, verify audio
   playback/capture, idle/active NPU jobs and repeated system sleep/resume.
   Record missing devices and all kernel warnings as failures.
3. Run the cuDLA qualifier against the exact candidate module artifact,
   including reuse, numerical outputs and retained-allocation counters.
4. With unpublished DSP clients removed, qualify checked NPU stop/reload and
   numerical execution again. Reject mismatched source versions or retained
   module/firmware leases; do not reset or force unload after a failure.
5. Explicitly boot DSP firmware using the matching ABI v5 bundle. Confirm all
   three ready replies, staging-release fields and provider links. Exercise
   the opt-in AFE route with real playback/capture and close/error cases.
6. With the retention option absent, published DSPs must still reject sleep in
   PM `prepare` without losing audio devices. With a separate candidate boot
   using `n1x_adsp.enable_retention_sleep=1`, qualify the ASoC-ordered DSP s2idle path
   described in [the DSP guide](audio.md#qualification-after-the-fresh-boot):
   `pm_test=devices` first, then real/repeated sleep, firmware IPC, audio and
   numerical NPU execution. All DSP DMA/provider leases must remain retained;
   failed D3 completion or resume must remain terminal. This is retention,
   not whole-core shutdown, lease release or removable published devices.
   Hibernate, deep sleep and legacy active clients without ASoC ordering must
   reject in `prepare`. Include running playback, CLOSE/OPEN reuse and ALSA
   recovery after sleep; see [audio qualification](audio.md).

Injected transport faults and allocation failures run in the hardware-free
actual-function harnesses. Do not manufacture mailbox errors or power faults
on a live published instance. AFE task STOP/CLOSE and IRQ disable are not
proof of whole-DSP DMA quiescence.


## Explicit DSP reload candidate

DSP 0.1.25, AFE 0.1.27 and provider ABI v5 add native shutdown and reclamation.
They also require `p16-dsp-shutdown-power.patch` in the booted kernel. Build and
source checks cannot qualify its firmware power-off contract. Preserve the
known-working boot and use [the complete reload procedure](audio.md#module-reload-qualification),
including the six PCM cases and numerical NPU execution after each of two
reloads. Kernel transport, provider, DSP and AFE failure tests must pass first.
The first transition from the old pinned driver still needs a matching boot;
replacing its on-disk module cannot add a callback to already-running code.
