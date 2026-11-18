# Kernel37 native boot and media gate — 18 November 2026

The ASUS ProArt P16 H7607BA (BIOS `H7607BA.300`) booted the staged
`7.2.8-37-rtx-spark-npu` UKI through a one-time UEFI `BootNext=0000` entry.
The boot ID is `add4e65c-7804-4e34-a887-b8646b467db3`. `BootCurrent` is
`0000`; the permanent BootOrder remains `0002,0001,2001,2002,2003`, with
Limine first and kernel36 still its default. The kernel37 UKI SHA256 is
`ff6472443b4e5e9f7690135717ae35f1e8a342c45259467b5a2ad2601931a6bc`.
All 13 package-owned platform modules still matched the staging manifest.

The NVIDIA RTX Spark N1X display stack works with driver `615.78.08`, including
`nvidia-smi` and Hyprland output on the built-in 3840×2400 eDP and 3840×2160
external DP monitors. The SCP, Pluton, NPU bootstrap, ADSP, SPI HID, ALS and
NVIDIA modules loaded. Lockdep initially reported `debug_locks: 1` with no
Lockdep warning. This confirms a native boot of the MMU notifier correction,
not yet a clean full-workload or suspend/resume qualification.

The installed FFmpeg NVENC probe failed H.264, HEVC and AV1 at
`NvEncOpenEncodeSessionEx` with error 21 (exit 187 each), as it did on
kernel36. The kernel correction alone did not make NVENC usable with driver
615.78.08. The installed GStreamer camera→Vulkan H.264 path recorded 60
decoded, unique frames. A V4L2 contention test got 120 primary frames,
correctly reported the second client busy, and recovered with 10 more frames.
The internal IR camera also delivered 30 GREY 360×360/15 frames. Camera pixels
were not retained in the test artifacts.

At 16:16:39, the first internal RGB FFmpeg capture triggered a new warning:

```text
DMA-API: xhci-hcd NVDA8001:00: mapping sg segment longer than device claims to support [len=94208] [max=65536]
WARNING: kernel/dma/debug.c:1231 at debug_dma_map_sg+0x490/0x590, CPU#9: ffmpeg/80187
dma_alloc_noncontiguous -> usb_alloc_noncoherent -> uvc_alloc_urb_buffers -> uvc_video_start_transfer
```

The internal camera's `32 × 2,940 = 94,080`-byte UVC buffer rounds up to
94,208 bytes across 23 pages, exceeding the XHCI DMA segment limit of 65,536
bytes. The earlier kernel36 warning was a *different* 98,304-byte allocation
on the external Logitech StreamCam's `NVDA8000:00` host. Both hosts therefore
need a UVC allocation fix. The native kernel37 boot is warned and cannot be
used as a warning-free physical suspend/resume qualification.

The [UVC candidate](../../kernel/uvc-urb-dma-segment-limit.patch) was built
offline against this kernel. Its [live module test](n1x-media-20261118/uvc-dma-live-kernel37.md)
passed RGB, IR and GStreamer/Vulkan capture with capped URBs and no new DMA
warning. The installed kernel37 package and default boot entry have not been
modified by that test. A fresh patched boot is still required.
