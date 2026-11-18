# Kernel38 UVC DMA-limit candidate: offline qualification

The ASUS ProArt P16 H7607BA candidate is `7.2.8-38-rtx-spark-npu` with the
existing MMU notifier Lockdep correction and the new UVC DMA segment cap.
The final ARM64 Image SHA256 is
`8fb6781cf43549c38631b60356a757cfa2749672dd7d4ebb7a07c03faf45fa74`.
The [receipt](kernel38-offline-20261118.json) pins all three package hashes,
the patch and packaged UVC module hashes, the 4,081 external-module inputs,
build logs and the exact kernel BTF identity.

Signed upstream source checks and package builds passed. The kernel package
contains the byte-identical Image that passed the [direct KVM smoke test](kernel38-image-smoke-20261118.md):
correct release, `debug_locks=1`, no warning and clean shutdown. Its
`uvcvideo.ko` is signed, has matching `vermagic` and BTF, and contains the
new DMA-limit diagnostic. All 8,490 in-tree packaged modules passed split-BTF
validation.

The matching NVIDIA 615.78.08 and P16 DSP, NPU provider, Pluton, SCP, ALS,
sensorhub and hwmon modules were rebuilt from pinned sources. All 8,507
in-tree and external modules passed split-BTF validation against the final
`vmlinux`. The 13 production external modules were packaged as
`linux-p16-platform-38-drivers-7.2.8-38-aarch64.pkg.tar.xz`; each module's
archived hash was checked against the build manifest. The development-only
validation modules are absent from that package.

No kernel38 package or module has been installed, no boot file has been
written, and no host suspend was requested by this build. The currently
loaded kernel37 UVC candidate passed a live internal-camera test, but it does
not qualify a fresh kernel38 boot. Native display, RGB/IR camera capture,
DMA/Lockdep warning scan, NVENC status and physical resume remain separate
gates before the candidate can be called supported and used.
