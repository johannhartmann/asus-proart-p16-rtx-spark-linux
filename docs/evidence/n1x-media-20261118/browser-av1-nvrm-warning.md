# NVRM allocation warning during Chrome AV1 playback

On 18 November 2026 at 13:26:04 CET, the kernel logged:

```text
NVRM: GPU0 nvCheckOkFailedNoLog: Check failed: Out of memory [NV_ERR_NO_MEMORY] (0x00000051) returned from _memdescAllocInternal(pMemDesc) @ mem_desc.c:1348
```

The line occurred during the 1280×720 AV1 browser qualification. The installed
`p16-video-chrome` run still reported `VaapiVideoDecoder`, a platform decoder,
96 played frames and zero drops in
[`browser-decode-p16-av1-720p.json`](browser-decode-p16-av1-720p.json).
A separate attempt to create an AV1 MP4 with the distribution's
`av1_vulkan` encoder had produced a bitstream that independent software
decoding rejected, so that fixture was discarded. The accepted browser
fixture was produced by `aomenc`, remuxed to MP4, and independently decoded
before browser playback. Other GPU workloads, including a vLLM engine, were
running at the time; the kernel line alone cannot attribute the allocation
failure to Chrome or the AV1 decoder.

An immediate [identical AV1 repeat](browser-decode-p16-av1-repeat-720p.json)
again played 96 frames through `VaapiVideoDecoder` without drops. No new NVRM,
Xid or IOMMU line appeared after 13:26:27 CET during that repeat. This
isolated repeat does not erase the first warning. Longer or concurrent
browser stability remains unqualified.

A later [20-second AV1 run](browser-decode-p16-av1-20s-720p.json) on the same
installed launcher played 480 frames with zero drops through
`VaapiVideoDecoder`, with `kIsPlatformVideoDecoder=true`. The kernel journal
between 13:35:01 and 13:35:34 CET had no NVRM, Xid or IOMMU line. This
improves the bounded stability evidence but does not establish hours-long or
post-resume operation.
