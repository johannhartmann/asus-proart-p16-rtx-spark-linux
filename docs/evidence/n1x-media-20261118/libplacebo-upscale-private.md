# Isolated libplacebo 7.387 FFmpeg scaling candidate

The installed FFmpeg/libplacebo filter fails before processing a frame with
API 360; [the native filter finding](ffmpeg-libplacebo-filter-kernel38.md)
identifies the rejected Vulkan queue flag. An **uninstalled** user-directory
candidate tests the newer API without replacing `libplacebo.so=360-64` used by
the installed mpv and FFmpeg packages.

libplacebo v7.387.0 was checked out with its pinned submodules at commit
`275f7dea27924cdd34ab2e6c20e448b6bc4fab65` and built with Meson 1.12.1,
Vulkan and shaderc enabled, demos/tests/OpenGL disabled. The private library
SHA256 is `06e24549966d3693d909e34bf3798bf151391f11625cb4bbc1f63d72ed10f8b7`.
FFmpeg 9.0.2 came from the already pinned source archive SHA256
`8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`.
Its isolated build used `--enable-libplacebo --enable-vulkan` and the private
pkg-config path and rpath; `ldd` resolves `libplacebo.so.387` to that private
directory. Binary SHA256:
`daac1bc065a2e8f3b9101e422218c44c01938f872ccc3f8d86a1480d9e1f1df2`.
No system package, library or boot file was changed.

[`check-libplacebo-upscale.py`](../../../scripts/check-libplacebo-upscale.py)
generated 60 deterministic 1280×720 NV12 frames, downsampled them to 640×360
with software Lanczos, then compared GPU libplacebo upscale against CPU
bicubic at 1280×720. All three GPU runs selected RTX Spark N1X, logged
libplacebo API 387, produced 60 full-sized distinct frames, and deleted raw
pixels after measurements. These are functional passes; they are not quality
acceptance or a steady-state latency result.

| GPU settings | Luma PSNR vs source | SSIM vs source | CPU bicubic control |
| --- | ---: | ---: | ---: |
| EWA Lanczos, unspecified raw color tags | 22.23 dB | 0.94565 | 35.68 dB / 0.96887 |
| EWA Lanczos, explicit limited BT.709 input/output | 33.60 dB | 0.95894 | 35.68 dB / 0.96887 |
| Spline36, explicit limited BT.709 | 33.78 dB | 0.96024 | 35.68 dB / 0.96887 |

The [untagged](libplacebo-upscale-private-20261118.json),
[BT.709 EWA](libplacebo-upscale-private-bt709-20261118.json), and
[BT.709 Spline36](libplacebo-upscale-private-spline36-20261118.json) JSON records
contain output hashes, frame samples, device/API evidence, sizes, PSNR, SSIM
and wall times. Color/range metadata materially changes the output, so any
integration must set it explicitly. On this one synthetic fixture, both
tagged GPU filters score below the CPU control. The roughly 1.8-second GPU
wall times include process startup, shader compilation and raw-file I/O;
they do not measure per-frame playback latency. Real-content visual review,
power/steady latency, package integration and installed application use are
still required before calling this an accepted scaling export.
