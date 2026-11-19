# UVC DMA allocation on both N1X USB hosts, native kernel38

On 19 November 2026, the running P16 remained on boot
`806fab11-2c93-426d-805b-8a82426047b8`, kernel
`7.2.8-38-rtx-spark-npu` and NVIDIA 615.78.08. The
[`run-p16-uvc-dma-trace.py`](../../../scripts/run-p16-uvc-dma-trace.py)
wrapper used one graphical Polkit authentication to enable UVC trace bit
1024. It ran the camera checker as the desktop user and restored the prior
trace value **0** afterward. Four ordinary FFmpeg V4L2 captures completed:
60 frames each from the internal RGB camera at 1280×720 and 1920×1080,
30 internal IR frames at 360×360 GREY, and 60 external StreamCam frames at
1920×1080 MJPEG. They discarded all frames through the null muxer. The
[raw result and command logs](uvc-dma-both-hosts-kernel38-installed/result.json)
remain unchanged.

| Host/interface | Mode | Trace allocation | Page-rounded bytes | DMA limit |
| --- | --- | --- | ---: | ---: |
| `NVDA8001:00`, `7-1:1.0` | RGB 720p and 1080p MJPEG | 22 × 2,940 bytes, five URBs each | 65,536 | 65,536 |
| `NVDA8001:00`, `7-1:1.2` | IR 360p GREY | 32 × 1,176 bytes, five URBs | 40,960 | 65,536 |
| `NVDA8000:00`, `2-1.1:1.0` | StreamCam 1080p MJPEG | 10 × 6,144 bytes, five URBs | 61,440 | 65,536 |

The window contained no new DMA, kernel warning, BUG, KASAN or NVRM Xid
line. The first checker returned `pass: false` **solely because its expected
StreamCam packet size was 3,072 bytes**, the camera's 720p MJPEG alternate
setting. The [earlier StreamCam trace](uvc-streamcam-urb-size-current-boot.json)
already measured 6,144 bytes for 1080p MJPEG on alternate setting 7.
The corrected checker now expects 6,144 bytes and a ten-packet cap for this
exact mode. Its [read-only recheck](uvc-dma-both-hosts-kernel38-recheck.json)
reparses the original trace lines, verifies the original allocation records,
pins the original JSON SHA256 and passes all capture, interface, packet-size,
DMA-limit and warning gates. Negative controls still reject a missing
StreamCam cap, a failed capture and a new kernel warning. No capture or
privileged trace write was repeated for the correction.

This qualifies the current-boot UVC allocation sizes for the P16's internal
RGB/IR host and the attached external host. It does not qualify a fresh boot
or physical suspend/resume. The external StreamCam is a host test, not a
claim that it is built into this laptop.
