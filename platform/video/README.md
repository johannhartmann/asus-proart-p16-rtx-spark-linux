# N1X FFmpeg codec candidate

`ffmpeg-n1x-video` builds FFmpeg 9.0.2 and the pinned FFmpeg NVIDIA codec
headers for ARM64. Its `ffmpeg-n1x`, `ffprobe-n1x` and `ffplay-n1x` executables coexist with
the distribution's `ffmpeg` and shared `libav*` libraries. This candidate
does not replace the default codecs or claim that an advertised N1X profile
works on this Linux driver. `ffplay-n1x` is an isolated SDL player that can
select the compiled `hevc_cuvid` decoder explicitly for HEVC 4:2:2 material.
Use `ffplay-n1x -enable_vulkan -vcodec hevc_cuvid FILE` to render with
libplacebo/Vulkan. The [candidate matrix](../../docs/evidence/n1x-media-20261118/ffplay-vulkan-candidate/hevc-pro-matrix.json)
shows 8/10/12-bit 4:2:2 frames reaching libplacebo as `nv16`, `p210le` and
`p212le`, respectively, without the SDL renderer's 4:2:0 conversion. The
[timed A/V test](../../docs/evidence/n1x-media-20261118/ffplay-vulkan-candidate/timed/hevc422-av-ffplay.json)
also passes with Vulkan enabled. This proves the renderer input path, not
the final display's bit depth or color accuracy.

Package release 6 maps the NVIDIA VA-API bridge's planar `Q416` surface to
FFmpeg `yuv444p16le` for HEVC 10/12-bit 4:4:4 decode. The isolated patched
binary returned 30 frames of a genuine 12-bit HEVC RExt 4:4:4 fixture with
pixels byte-identical to software readback. Use `hwdownload,format=yuv444p16le`
for this path; forcing `yuv444p` yields incorrect bytes. The
[readback evidence](../../docs/evidence/n1x-media-20261118/hevc44412-vaapi-q416-candidate-kernel38.json)
was obtained with the local candidate before package installation. Normal
`ffmpeg` remains the distribution binary; package installation and application
use require separate qualification.
The installed matrix also produced two NVIDIA memory-allocation warnings
during a separate mpv 4:4:4 playback case; see the [incident record](../../docs/evidence/n1x-media-20261118/nvrm-memory-warning.md)
before treating the package as qualified for longer or concurrent workloads.

Build with `MAKEFLAGS=-j16 makepkg --cleanbuild --noconfirm` in this directory.
The source archives and SHA256 hashes are pinned in `PKGBUILD`; matching
NVIDIA kernel and userspace components remain required. The package check
verifies compiled features only. Run the [media qualification](../../missing_parts.md)
on the exact installed candidate before deploying it as a default or claiming
an application uses NVENC/NVDEC.

On the P16 with NVIDIA 615.78.08, this candidate exposes all three NVENC
encoders but `h264_nvenc` cannot open a session: `OpenEncodeSessionEx failed:
incompatible client key (21)`. The [raw log](../../docs/evidence/n1x-media-20261118/nvenc-h264.log)
is retained. The system FFmpeg's Vulkan Video encoders successfully produced
H.264, HEVC, and AV1 on this machine; they are a separate Linux API and do not
establish that the NVENC API works. Keep this candidate isolated pending a
driver/API fix and full end-user recording qualification.
The [installed NVENC check](../../docs/evidence/n1x-media-20261118/installed-nvenc/installed-nvenc.json)
confirms error 21 for H.264, HEVC and AV1 with `/usr/bin/ffmpeg-n1x`.

The selected configure flags keep core FFmpeg codecs and link the existing
system x264, x265 and libvpx libraries for test fixtures. Other distribution
FFmpeg features are not guaranteed by this isolated binary. If Omarchy elects
to replace its normal FFmpeg package, rebase the distribution recipe and
preserve its full feature/dependency set and `libav*` ABI; do not substitute
this candidate for it.
