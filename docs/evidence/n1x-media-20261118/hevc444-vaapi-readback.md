# HEVC 10/12-bit 4:4:4 VA-API readback on kernel 38

Run `scripts/check-hevc444-vaapi-readback.py` with the pinned x265 10-bit or
12-bit binary. It generates a 30-frame 320×180 HEVC RExt `yuv444p10le` or
`yuv444p12le` fixture and
removes all temporary source and output pixels after hashing and comparison.
All runs used boot `806fab11-2c93-426d-805b-8a82426047b8`, NVIDIA 615.78.08,
`libva-nvidia-driver 0.0.18-1`, and one FFmpeg decoder thread.

| FFmpeg binary | 16-bit planar VA-API readback for 10/12-bit fixtures | Forced 8-bit `yuv444p` |
| --- | --- | --- |
| Distribution `/usr/bin/ffmpeg` 9.0.2-2 | `hwdownload,format=yuv444p16le` fails: invalid output format | 30 frames, but bytes differ from software output in all Y/U/V planes |
| Isolated FFmpeg 9.0.2 candidate with [Q416 mapping](../../../platform/video/0001-vaapi-map-q416-planar-16bit-444.patch) | 30 frames, 10,368,000 bytes per fixture, byte-identical to software `yuv444p16le` | Still incorrect when forced directly; download 16-bit before any conversion |

The [12-bit distribution result](hevc44412-vaapi-readback-kernel38.json) and
[candidate result](hevc44412-vaapi-q416-candidate-kernel38.json) record fixture
and binary hashes, frame counts, exact sizes, backend selection and format
errors. The candidate's 16-bit output SHA256 equals software output:
`92685f3a6f0025a199d391d89b7c14de6ae16043c95d139c8043f8f534bc7e40`.
The [10-bit distribution](hevc44410-vaapi-readback-kernel38.json) and
[package](hevc44410-vaapi-q416-package-kernel38.json) runs use an identical
10-bit fixture hash and repeat the failure/pass split. The 10-bit package
output SHA256 equals software output:
`c02d9072fa8185d4f6a02fae904ee7f1344b5084ab4848ff56d782c6d83c39aa`.
`p410le`/`yuv444p10le` and `p412le`/`yuv444p12le` are not directly
downloadable with either binary;
the bridge exports 16-bit planar Q416 surfaces for 10/12-bit 4:4:4.

The [NVIDIA VA-API bridge PR #225](https://github.com/elFarto/nvidia-vaapi-driver/pull/225)
documents Q416 and the required FFmpeg mapping. FFmpeg 9.0.2 on this machine
lacks that mapping, while installed libva defines `VA_FOURCC_Q416`. The
package recipe now applies a scoped FFmpeg patch and produces an isolated
`ffmpeg-n1x` candidate; the running distribution FFmpeg and libraries are
untouched. The reproducible `ffmpeg-n1x-video 9.0.2-6` package built from
checksum-verified sources. Its archive SHA256 is
`e7b83a47d507d1818609164435aaa9980aa9519210e10df7bab24daeb1965cd9`.
The extracted package binary SHA256 is
`6a82cf0c63e8aae9918281135a7091449308346c1f834fa5f8a0a56a2292c3ea`;
its separate [hardware readback result](hevc44412-vaapi-q416-package-kernel38.json)
also matches all 30 software frames. The package is not installed yet.
The [timed 12-bit FFplay test](hevc44412-vaapi-player-kernel38/hevc44412-vaapi-playback.json)
qualifies application playback through VA-API and libplacebo for both the
installed 9.0.2-5 player and the extracted 9.0.2-6 player. This does not
exercise FFmpeg's CPU readback conversion; package installation and its
installed readback regression are separate gates.
The later [9.0.2-7 package](libplacebo-api360-compat.md) retains this Q416
patch. Its extracted binary again matches all 30 software frames for
[10-bit](hevc44410-vaapi-q416-package7-kernel38.json) and
[12-bit](hevc44412-vaapi-q416-package7-kernel38.json) input. The installed
package is still 9.0.2-5 while graphical authentication is pending.

The separate [8-bit 4:4:4 VA-API readback](hevc4448-vaapi-readback-kernel38.json)
uses the installed distribution FFmpeg, the installed x265 8-bit encoder,
and a 30-frame HEVC RExt `yuv444p` fixture. All 5,184,000 decoded bytes
match software output. The log checks select NVIDIA's direct VA-API backend
and `vaapi` frames. The [source](hevc4448-vaapi-readback-kernel38-source.log),
[encode](hevc4448-vaapi-readback-kernel38-encode.log),
[software](hevc4448-vaapi-readback-kernel38-software.log) and
[VA-API](hevc4448-vaapi-readback-kernel38-vaapi.log) command logs are retained
without the temporary pixels. This 8-bit case does not depend on Q416 or
the isolated FFmpeg package.
