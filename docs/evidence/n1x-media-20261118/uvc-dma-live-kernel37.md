# UVC DMA allocation candidate, native kernel37 live test

On the ASUS ProArt P16 H7607BA, kernel `7.2.8-37-rtx-spark-npu` and NVIDIA
615.78.08, the original `uvcvideo` module was unloaded and the offline-built
[candidate](../../../kernel/uvc-urb-dma-segment-limit.patch) was inserted with
matching kernel version and BTF. The first direct `insmod` attempt lacked
three modules auto-removed by `modprobe -r`; after loading `uvc`,
`videobuf2_v4l2` and `videobuf2_vmalloc`, the candidate loaded and all four
internal V4L2 camera nodes returned. This was a live module substitution;
the installed kernel37 package and UKI still contain the original UVC module.

The [test record](uvc-dma-live-kernel37.json) pins the candidate module and
patch hashes, frame counts, trace lines and warning scan. The raw capture and
GStreamer logs are in [uvc-dma-live-kernel37/](uvc-dma-live-kernel37/). With
trace bit 1024:

| Capture | Result | UVC allocation |
| --- | --- | --- |
| Internal RGB MJPEG 1280×720/30 | 60 frames, exit 0 | 5 URBs of `22 × 2,940 = 64,680` bytes |
| Internal RGB MJPEG 1920×1080/30 | 60 frames, exit 0 | Same capped URBs |
| Internal IR GREY 360×360/15 | 30 frames, exit 0 | 5 URBs of `32 × 1,176 = 37,632` bytes; no cap needed |
| Installed GStreamer/Vulkan H.264 camera recorder | 60 decoded and unique frames | Capped RGB URBs |

The RGB allocation rounds to exactly 65,536 bytes, the XHCI host's advertised
maximum. The kernel log contains no new `DMA-API`, `WARNING`, `BUG` or `KASAN`
line in this test window. The trace parameter was restored from 1024 to 0.
The external Logitech StreamCam was disconnected, so its capture under the
patch has not been measured. The boot already contains the earlier internal
camera DMA warning from the original module and therefore cannot certify a
clean boot or physical suspend/resume. Durable integration requires a new
kernel build and fresh boot, followed by both camera and application tests.
