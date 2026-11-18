# FFplay Vulkan/libplacebo HEVC 4:2:2 path

FFmpeg 9.0.2's existing FFplay Vulkan renderer is guarded by
`CONFIG_LIBPLACEBO`. Package `ffmpeg-n1x-video 9.0.2-4` did not enable that
configure option, so `-enable_vulkan` logged a fallback to SDL and converted
CUVID `nv16`/`p210le`/`p212le` frames to `IYUV` 4:2:0.

Package recipe 9.0.2-5 enables Vulkan and libplacebo, declares `libplacebo`
as a runtime dependency and `vulkan-headers` as a build dependency. The local
build used Arch Linux ARM `vulkan-headers 1:1.4.363.0-1` extracted into an
isolated include path; its detached signature verified with the locally
trusted Arch Linux ARM Build System key
`68B3537F39A313B3E574D06777193F152BDBE6A6`. Header package SHA256:
`ed90fb67e0e2c49f9871f5f2d7d62f9e41b58e058481400bf8da580225cde88f`.
The local `makepkg --nodeps --cleanbuild` run used that verified include path;
a normal build installs the declared `vulkan-headers` dependency. The
FFmpeg and NVIDIA codec-header source checksums passed `makepkg --verifysource`.

The built package archive SHA256 is
`2fdc1e75ae36cff2ccfcfe56cb8d5e53dc41642bd47d7ff5d26c7b611e2a6c30`.
The extracted and installed `ffplay-n1x` SHA256 is
`7cfad747713ae6c2c156c5cf57370f5694da0ab5f9c768589f4ac6b63aac59bd`.
The [package binary matrix](ffplay-vulkan-package/hevc-pro-matrix.json) shows
that all three generated HEVC 4:2:2 fixtures decoded with CUVID; their decoded
pixel hashes matched software. The extracted package's Vulkan/libplacebo
renderer received `nv16` (8-bit), `p210le` (10-bit) and `p212le` (12-bit)
without an observed `auto_scale` filter or SDL `IYUV` texture. The older
installed SDL binary in the same matrix is the conversion control.

A [six-second A/V package-binary test](ffplay-vulkan-package/timed/hevc422-av-ffplay.json)
also reached EOF with CUVID, libplacebo and AAC processing. Its 185 sampled
A/V offsets were at most 44 ms. This establishes a timed application path;
it does not measure the physical display's bit depth, HDR metadata or color
accuracy. The package was installed through graphical Polkit authentication.
The [installed matrix](installed-ffplay-vulkan/hevc-pro-matrix.json) repeats
all three 4:2:2 depths with the same binary SHA256, and the
[installed A/V run](installed-ffplay-vulkan/timed/hevc422-av-ffplay.json) reached
EOF with 184 A/V samples at most 27 ms apart. The distribution FFmpeg package
remained at 9.0.2-2. No new NVRM/Xid line appeared during the bounded 9.0.2-5
renderer tests; the earlier [allocation warning](nvrm-memory-warning.md)
keeps longer and concurrent stability open.

Rebuild on a system with the declared build dependencies installed:

```sh
cd platform/video
MAKEFLAGS=-j16 makepkg --cleanbuild --noconfirm
```

Run the HEVC 4:2:2 path with:

```sh
ffplay-n1x -enable_vulkan -vcodec hevc_cuvid FILE
```
