# Kernel38 direct KVM image smoke test

The [reproducible smoke check](../../scripts/check-kernel-image-smoke.py)
booted the exact candidate ARM64 Image SHA256
`8fb6781cf43549c38631b60356a757cfa2749672dd7d4ebb7a07c03faf45fa74`
under QEMU/KVM on the N1X host. Its static init mounted devtmpfs and proc,
read `uname` and `/proc/lockdep_stats`, then powered off. The
[result](kernel38-image-smoke-20261118.json) and [UART log](kernel38-image-smoke-20261118.uart.log)
show `7.2.8-38-rtx-spark-npu`, `debug_locks=1`, QEMU exit 0 and no
`WARNING`, `BUG` or `KASAN` line. No host module was loaded and no host PM
operation or boot-file write occurred.

The completed kernel package
`linux-p16-platform-38-7.2.8-38-aarch64.pkg.tar.zst` has SHA256
`ef460d584ce5b283188ed983ce5407247448170f3faa6329d6905dee1ae26e7d`;
its archived `vmlinuz` byte hash equals the tested Image. The matching
headers package SHA256 is
`b0682c0c5693965bc14d797a65410b22384b7fca18e937d2db42ca679032d746`.
All 8,490 in-tree packaged modules passed split-BTF validation against the
final `vmlinux`, with base BTF SHA256
`91aeed91e77746e07706770b1d0810f290f447cab58dcbcc86e5304393dd1768`.
The packaged `uvcvideo.ko` SHA256 is
`8c2c4daf8ca5b3e6481bae2546d5992fb2a0afdeb9d5bddf53835a3c54f43c0f`;
it contains the new URB-limit diagnostic, matching release `vermagic` and
split BTF. The signed packaged module differs from its unsigned build object,
as expected.

This is a **direct kernel** boot with a minimal initramfs. It does not test
the packaged UKI, platform modules, cameras, NVIDIA display or physical
suspend/resume. Those gates follow the complete package and driver build.
