# N1X FFmpeg codec candidate

`ffmpeg-n1x-video` builds FFmpeg 9.0.2 and the pinned FFmpeg NVIDIA codec
headers for ARM64. Its `ffmpeg-n1x`, `ffprobe-n1x` and `ffplay-n1x` executables coexist with
the distribution's `ffmpeg` and shared `libav*` libraries. This candidate
does not replace the default codecs or claim that an advertised N1X profile
works on this Linux driver. `ffplay-n1x` is an isolated SDL player that can
select the compiled `hevc_cuvid` decoder explicitly for HEVC 4:2:2 material.
Version 9.0.2-4 is installed on the reference P16. The installed binary passed
the [8/10/12-bit HEVC 4:2:2 matrix](../../docs/evidence/n1x-media-20261118/installed-ffplay/hevc-pro-matrix.json)
and a [timed HEVC 4:2:2/AAC playback](../../docs/evidence/n1x-media-20261118/installed-ffplay/hevc422-av-ffplay.json).
It uses CUVID for decode, but FFplay's SDL renderer converts the output to
8-bit 4:2:0 `IYUV`, so display fidelity remains unqualified.
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
