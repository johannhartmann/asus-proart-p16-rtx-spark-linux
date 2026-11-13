# Temporary kernel31 AFE migration

The permanent fix is `kernel/p16-afe-const-irq-shutdown.patch`: closing a PCM
must clear its borrowed substream pointer even when its fixed IRQ stays reserved.
The sanitizer regression is `python3 platform/dsp/afe/test_const_irq.py`.

This livepatch exists only to qualify unloading the already running
`7.2.8-31-rtx-spark-npu` / AFE 0.1.27 instance without another reboot. It is
not installed by any package, service or boot configuration. Later kernels
must use the permanent source patch. Do not enable it automatically.

Build against the exact running headers and exact AFE 0.1.27 source directory:

```sh
make -C /usr/lib/modules/7.2.8-31-rtx-spark-npu/build \
  M="$PWD/platform/dsp/livepatch" AFE_SOURCE=/absolute/path/to/mt8901 \
  AFE_SRCVERSION="$(modinfo -F srcversion snd_soc_mt8901_afe)" W=1 modules
python3 scripts/verify-module-btf.py --help
python3 platform/dsp/livepatch/check-layout.py \
  --vmlinux /usr/lib/modules/7.2.8-31-rtx-spark-npu/build/vmlinux \
  --afe /usr/lib/modules/7.2.8-31-rtx-spark-npu/updates/dkms/snd-soc-mt8901-afe.ko \
  --livepatch platform/dsp/livepatch/n1x_afe_const_irq_fix.ko
```

Before loading, validate split BTF against that vmlinux and require an exact
six-structure layout match. The source refuses other kernels, boards or AFE
source revisions. Its migration requires an unbound machine card and clears
only already-closed, published fixed-IRQ borrowers; it does not free memory
or program hardware. Use it only to continue the checked maintenance helper
after that specific stale-borrower failure. Never force a livepatch transition,
module removal, DMA release or a firmware reset. The common MediaTek module
remains pinned by the livepatch during subsequent DSP/AFE reloads.

On 13 November 2026, an isolated KVM test reproduced the old stale borrower and
verified both fixed and dynamic IRQ behavior after this livepatch. The native
transition then completed, migrated exactly two stale borrowers and allowed a
full checked DSP/AFE unload, reload and all three firmware startups in one boot.
