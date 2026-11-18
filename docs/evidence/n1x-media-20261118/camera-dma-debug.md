# UVC DMA-debug warning on the N1X XHCI host — 18 November 2026

The current kernel36 boot recorded one warning at 08:29:40 while starting a
UVC stream:

```text
DMA-API: xhci-hcd NVDA8000:00: mapping sg segment longer than device claims to support [len=98304] [max=65536]
debug_dma_map_sg -> dma_alloc_noncontiguous -> usb_alloc_noncoherent
                 -> uvc_alloc_urb_buffers -> uvc_video_start_streaming
```

The warning names host `NVDA8000:00`, which carries an attached Logitech
StreamCam. The internal ASUS RGB and IR cameras are on `NVDA8001:00`. All
use `uvcvideo`, but the host identity means this warning cannot be attributed
to the built-in P16 camera. It does mean this boot cannot be called free of
DMA-debug warnings.

An [upstream XHCI/MediaTek discussion](https://lists.infradead.org/pipermail/linux-mediatek/2023-June/064737.html)
reports the exact 98304/65536 UVC warning. The maintainers discuss whether
the DMA-debug check on `dma_alloc_noncontiguous()` is misplaced and caution
against raising every host controller's advertised segment limit merely to
silence it. The P16's warning is on an ACPI `xhci-hcd NVDA8000:00` device;
the upstream report is a different board. This is a relevant mechanism, not
proof that one upstream change resolves the P16 case.

A [bounded trace of the StreamCam](uvc-streamcam-urb-size-current-boot.json)
now identifies the exact allocation: MJPEG 1280×720/30 used five URBs of
`32 × 3,072 = 98,304` bytes each on `NVDA8000:00`. The 1920×1080 MJPEG and
1280×720 YUYV modes requested still larger URBs. All three captured 30
frames. A separate [internal camera trace](uvc-urb-size-current-boot.json)
measured 94,080-byte RGB URBs and 37,632-byte IR URBs on `NVDA8001:00`; its
page-rounded RGB size also equals 98,304 bytes, but it is a different USB
host and cannot explain the recorded `NVDA8000:00` warning. Both temporary
trace windows ended with the setting restored to zero. Neither produced a
*new* DMA warning on this already warned boot.

An [uninstalled UVC candidate](../../../kernel/uvc-urb-dma-segment-limit.patch)
caps noncoherent URB allocations to the host's advertised DMA segment size.
It applies without fuzz to the kernel37 source and compiles as a module with
matching vermagic and split BTF; the [offline receipt](uvc-dma-candidate-offline.json)
pins its source and module hashes. Its packet cap and frame throughput have not
been tested on the StreamCam or the internal camera; no kernel or running
module contains this patch yet.

Before installing the candidate, reproduce with a fresh boot. Compare capture
frame integrity and throughput with and without the UVC buffer-size limit,
and check the DMA/IOMMU debug results on that same Image. Keep the XHCI
segment limit truthful. A successful camera recording remains a separate
application result.

This boot also has a distinct NVIDIA UVM Lockdep warning from 17 November
16:47:15. A physical suspend test performed now would not provide a clean
Lockdep qualification, even if camera capture worked after resume. The UVM
warning is not attributed to this UVC allocation.
