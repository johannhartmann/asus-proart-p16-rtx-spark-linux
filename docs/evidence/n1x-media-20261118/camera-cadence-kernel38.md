# Native kernel38 camera cadence and exposure control

The internal ASUS RGB camera is on USB 2.0 host `NVDA8001:00`. V4L2 reports
MJPEG 1280×720/30 and `exposure_dynamic_framerate=1` (factory default 0).
The [120-second Vulkan Video/NVOFA run](nvof-120s-kernel38.md) produced
3,585 source frames with 15 isolated 66–67-ms gaps, then processed every
available pair. To separate camera delivery from the Vulkan encoder, the
[`check-p16-camera-cadence.py`](../../../scripts/check-p16-camera-cadence.py)
probe recorded MJPEG through V4L2 and copied packets into a temporary
Matroska file without video encoding. It deleted each file after measuring
decoded frame timestamps.

With the camera's existing dynamic-framerate value 1, the [120-second direct
V4L2 recording](v4l2-cadence-kernel38-default.json) yielded only **1,419**
decodable frames. It began near 30 fps, then slowed after about 10.8 seconds;
1,087 timestamp gaps exceeded 50 ms. FFmpeg's final progress reported
1,421 input packets at about 12 fps over 120 seconds. No matching USB or
DMA-debug warning appeared in the kernel journal.

Setting `exposure_dynamic_framerate=0` temporarily gave **903** decodable
frames in [30 seconds](v4l2-cadence-kernel38-fixed30s.json), with one 100-ms
gap, and **3,616** decodable frames in [120 seconds](v4l2-cadence-kernel38-fixed.json),
with one 100-ms gap near 114 seconds. FFmpeg reported 3,618 input packets
for the longer fixed-rate run and two `Dequeued v4l2 buffer contains
corrupted data` messages. The probe restored the original control value 1
in `finally` and verified the readback. These results strongly associate
the large sustained rate collapse with the camera's dynamic-exposure frame
rate setting, while the remaining corrupt frames and short gaps still need
USB/V4L2 attribution.

A separate [120-second Vulkan Video recording with fixed exposure cadence](vulkan-fixed120s-kernel38.json)
produced exactly **3,600 decodable H.264 frames** with 33–34-ms output gaps
and no output gap over 50 ms. FFmpeg nevertheless reported `dup=0 drop=16`.
The initial checker marked the smooth output as a pass; the evidence JSON
reclassifies the stricter lossless-input gate as failed, and the checker now
requires zero duplicates and drops. This is a usable 30-fps encoded output,
but it does not establish that every camera input frame was retained.

Fixed cadence may reduce low-light exposure. The control is therefore kept
as an explicit recording option; no global camera setting was changed. The
direct V4L2 result and FFmpeg's Vulkan input-drop counter leave lossless
capture open. A later test must attribute the remaining corrupt buffers and
drops at USB/V4L2 and FFmpeg before claiming a flawless long camera source.
