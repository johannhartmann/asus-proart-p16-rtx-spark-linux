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
attribution.

The lower-level [V4L2 buffer-sequence test](v4l2-sequence-kernel38.json)
then captured **3,600 consecutive MJPEG buffers** in 119.834 seconds with
`exposure_dynamic_framerate=0`, bypassing FFmpeg and retaining no image data.
Buffer sequence numbers ran from 1 through 3,600 without a gap; all buffers
had nonzero size. Their monotonic sensor timestamps differed by 29.698–36.444
ms, with no gap above 50 ms. V4L2 reported no dequeue error and the kernel
logged no new warning. The control returned to its original value 1. This
qualifies buffer delivery and timing in this run; `v4l2-ctl` did not decode
the MJPEG payload or validate its pixels.

A separate [3,600-frame live MJPEG decode](mjpeg-decode-kernel38.json) passed
through FFmpeg to the Null output in 119.954 seconds, with no corrupt-payload
message or new kernel warning. With input timestamps preserved, the Null
muxer logged 35 non-increasing DTS warnings. The checker initially treated
all of those as decode errors; the recorded result separates the passing
decode gate from the failing timestamp-mux gate. This does not prove every
camera frame is unique or that a real container can preserve the source
timestamps without correction.

A separate [120-second Vulkan Video recording with fixed exposure cadence](vulkan-fixed120s-kernel38.json)
produced exactly **3,600 decodable H.264 frames** with 33–34-ms output gaps
and no output gap over 50 ms. FFmpeg nevertheless reported `dup=0 drop=16`.
The initial checker marked the smooth output as a pass; the evidence JSON
reclassifies the stricter lossless-input gate as failed, and the checker now
requires zero duplicates and drops. This is a usable 30-fps encoded output,
but it does not establish that every camera input frame was retained in the
encoded output. A 30-second Vulkan run with `-fps_mode passthrough` and the
same temporary exposure setting wrote 904 frames; its encoded timestamps had
four 66–67-ms gaps and eight non-increasing steps, with no corruption warning.
This supports FFmpeg's constant-30-fps resampling as a cause of the logged
`drop` count. It does not prove that all MJPEG payloads are valid or that
the remaining gaps originate in one specific component.

Fixed cadence may reduce low-light exposure. The control is therefore kept
as an explicit recording option; no global camera setting was changed. The
direct V4L2 sequence and MJPEG decode runs support sustained buffer delivery
and decodability, while the prior packet-copy corruption, timestamp mux
warnings and Vulkan resampling observations leave end-to-end lossless capture
open. A later test must distinguish sporadic input errors from output-rate
conversion and produce monotonically timed application output.
