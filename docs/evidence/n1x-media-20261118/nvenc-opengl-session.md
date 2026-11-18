# NVENC OpenGL session on the P16

The [direct EGL/OpenGL probe](nvenc-opengl-session.json) ran on 18 November
2026 with NVIDIA 615.78.08 and the P16's PCI `10de:2e03` RTX Spark N1X. The
probe creates a current NVIDIA OpenGL context on the actual N1X, obtains the
NVENC API function table, and calls `NvEncOpenEncodeSessionEx` with
`NV_ENC_DEVICE_TYPE_OPENGL` and a null device pointer, as required by
[NVIDIA's Linux API guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-video-encoder-api-prog-guide/index.html#opengl).
It does not submit a frame because session creation fails first.

Both pinned header versions compiled and reached the API call:

| `nv-codec-headers` | NVIDIA GL renderer | API instance | Open session |
| --- | --- | ---: | ---: |
| 12.2.72.0 | RTX Spark N1X, 6144-core | 0 | 21 |
| 13.1.15.0 | RTX Spark N1X, 6144-core | 0 | 21 |

The result repeats the installed FFmpeg and independent CUDA-device probe's
status 21 at the same function. An OpenGL device type and older API headers
therefore do not open an encoder session on this driver. The probe deliberately
exits nonzero; `pass=false` is an unresolved qualification failure. Reproduce
with:

```sh
python3 scripts/check-nvenc-opengl-session.py \
  --headers-12-2 /path/to/nv-codec-headers-n12.2.72.0 \
  --headers-13-1 /path/to/nv-codec-headers-n13.1.15.0 \
  --output docs/evidence/n1x-media-20261118/nvenc-opengl-session.json
```

A [separate ARM64 RTX 5050 report](https://forums.developer.nvidia.com/t/rtx-5050-on-arm64-cix-p1-nvenc-fails-with-error-21-on-driver-615-71-09-works-on-610-57-04/382838)
observed a working 610.57.04 NVENC session, error 21 on 615.71.09, and
recovery after downgrading to 610.57.04. That machine is not an N1X, so the
result only motivates a driver-version test here. NVIDIA's official
[Linux-aarch64 620.70.06 archive](https://download.nvidia.com/XFree86/Linux-aarch64/620.70.06/)
and [supported GPU list](https://download.nvidia.com/XFree86/Linux-aarch64/620.70.06/README/supportedchips.html)
include N1X PCI ID `2E03`. The public notes inspected here do not establish
that NVENC status 21 is fixed in 620.70.06. No driver package or running kernel
module was changed for this probe; the 620 stack needs an isolated matching
kernel-module/userspace/firmware build and rollback route before a real test.
