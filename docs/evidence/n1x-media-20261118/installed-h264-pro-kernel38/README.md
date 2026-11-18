# H.264 pro-format matrix on native kernel 38

[`h264-pro-matrix.json`](h264-pro-matrix.json) and the per-case raw logs come
from `scripts/check-h264-pro-matrix.py` on the running NVIDIA 615.78.08 stack.
Four 30-frame H.264 fixtures were encoded with installed libx264 at 320×180:
High 4:2:2 and High 4:4:4 Predictive, each at 8 and 10 bits. Temporary
pixel and video files were deleted after hashing.

| Profile | CUVID result | Installed FFplay Vulkan result | VA-API control |
| --- | --- | --- | --- |
| High 4:2:2 8-bit | 30 frames, 3,456,000 bytes identical to software; `nv16` surface | Timed clip to EOF; libplacebo receives `nv16` | Device opens, decoder output stays software `yuv422p` |
| High 4:2:2 10-bit | 30 frames, 6,912,000 bytes identical to software; `p210le` surface | Timed clip to EOF; libplacebo receives `p210le` | Device opens, decoder output stays software `yuv422p10le` |
| High 4:4:4 Predictive 8-bit | CUVID capability reports unsupported and rejects the profile | Skipped after negative capability query | Software `yuv444p` output, no VA-API frames |
| High 4:4:4 Predictive 10-bit | CUVID capability reports unsupported and rejects the profile | Skipped after negative capability query | Software `yuv444p10le` output, no VA-API frames |

The 4:2:2 decoder and installed application path are functional for these
bounded clips. VA-API's successful process exit is a software fallback for
all four pro-format controls; the installed `vainfo` likewise advertises no
H.264 High 4:2:2 or High 4:4:4 profile. The 4:4:4 CUVID result is an explicit
negative capability on this driver/device, not a general H.264 failure.
Physical display precision, long playback and post-resume use remain open.
