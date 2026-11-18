# UVC DMA-debug warning on the N1X XHCI host — 18 November 2026

The current kernel36 boot recorded one warning at 08:29:40 while starting a
UVC stream:

```text
DMA-API: xhci-hcd NVDA8000:00: mapping sg segment longer than device claims to support [len=98304] [max=65536]
debug_dma_map_sg -> dma_alloc_noncontiguous -> usb_alloc_noncoherent
                 -> uvc_alloc_urb_buffers -> uvc_video_start_streaming
```

The installed P16 RGB and IR cameras use `uvcvideo`; capture and graphical
browser preview have produced varying frames. The warning therefore does not
by itself establish corrupted frames or a failed USB transfer. It does mean
this boot cannot be called free of DMA-debug warnings.

An [upstream XHCI/MediaTek discussion](https://lists.infradead.org/pipermail/linux-mediatek/2023-June/064737.html)
reports the exact 98304/65536 UVC warning. The maintainers discuss whether
the DMA-debug check on `dma_alloc_noncontiguous()` is misplaced and caution
against raising every host controller's advertised segment limit merely to
silence it. The P16's warning is on an ACPI `xhci-hcd NVDA8000:00` device;
the upstream report is a different board. This is a relevant mechanism, not
proof that one upstream change resolves the P16 case.

Before changing the kernel, reproduce with a fresh boot and identify the
precise camera, format and URB size. Compare capture frame integrity and
throughput with and without a bounded UVC buffer-size candidate, and check
the DMA/IOMMU debug results on that same Image. Keep the XHCI segment limit
truthful. A successful camera recording remains a separate application result.

This boot also has a distinct NVIDIA UVM Lockdep warning from 17 November
16:47:15. A physical suspend test performed now would not provide a clean
Lockdep qualification, even if camera capture worked after resume. The UVM
warning is not attributed to this UVC allocation.
