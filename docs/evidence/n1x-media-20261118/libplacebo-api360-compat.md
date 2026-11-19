# FFmpeg/libplacebo API 360 compatibility candidate on N1X

On native kernel 7.2.8-38 and NVIDIA 615.78.08, FFmpeg 9.0.2 rejects the
Vulkan queue's transfer flag before its `libplacebo` filter processes any
frame when built against installed libplacebo API 360. The earlier
[GDB finding](ffmpeg-libplacebo-filter-kernel38.md) located the exact check.
[Package patch 0002](../../../platform/video/0002-libplacebo-import-vulkan-queues-api360.patch)
omits the unavailable `pl_vulkan_queue.flags` field for APIs below 365 while
leaving the newer API path untouched. The patch applied without fuzz to the
pinned FFmpeg 9.0.2 archive.

An isolated build linked to `/usr/lib/libplacebo.so.360` processed one frame
and then [60 tagged Spline36 frames](libplacebo-upscale-api360-compat-20261118.json)
on the N1X. A clean `ffmpeg-n1x-video 9.0.2-7` build from checksum-verified
sources produced archive SHA256
`5eaba6ed368abed5677841cc2a5787f12b7604fc2a364d5119c55db2954ddda9`.
The build used `makepkg --nodeps` because the `vulkan-headers` build dependency
is absent from the running root. Headers version 1.4.363.0-1 were extracted
in a user directory from the configured Arch ARM mirror and supplied through
`CPATH`; the downloaded archive SHA256 is
`ed90fb67e0e2c49f9871f5f2d7d62f9e41b58e058481400bf8da580225cde88f`.
No header package or runtime library was installed for this build.
The extracted FFmpeg binary SHA256 is
`9e0a2fe0939faac9cfbc440a179d7deb5bafd3c1c781411f77092cb81f171314`;
`ldd` resolves `libplacebo.so.360` to the installed library. Its
[60-frame filter comparison](libplacebo-upscale-api360-package7-20261118.json)
passes with 60 distinct GPU output frames, PSNR Y 33.78 dB and SSIM 0.96023.
The CPU bicubic control scores 35.68 dB and 0.96887 on this synthetic source.
The API 360 output and earlier private API 387 output differ slightly but
have nearly identical aggregate metrics. Neither result qualifies subjective
image quality or steady-state GPU speed.

Three additional tagged API 360 filter runs all processed 60 frames:
[Lanczos](libplacebo-upscale-api360-package7-lanczos-20261118.json) scored
33.79 dB / 0.96014,
[EWA Lanczos sharp](libplacebo-upscale-api360-package7-ewa_lanczossharp-20261118.json)
33.66 dB / 0.95934, and
[Spline64](libplacebo-upscale-api360-package7-spline64-20261118.json)
33.79 dB / 0.96027. None beats the CPU bicubic control on this source, so
there is no quality-based default change from this test.

The same extracted package binary passed [10-bit](hevc44410-vaapi-q416-package7-kernel38.json)
and [12-bit](hevc44412-vaapi-q416-package7-kernel38.json) Q416 VA-API readback:
30 `yuv444p16le` frames per case match software bytes. The
[timed player regression](hevc44412-vaapi-player-package7-kernel38/hevc44412-vaapi-playback.json)
passed in both CUVID and VA-API modes against the installed 9.0.2-5 control
and extracted 9.0.2-7 player. The first attempt was invalid because both
monitors had DPMS off under Omarchy's screensaver; the test now checks DPMS
before starting. Waking the monitors, without unlocking or changing config,
let all four playback paths reach EOF.

After graphical installation on the same kernel38/615 boot, `ffmpeg-n1x-video
9.0.2-7` reports 12 files and zero altered files under `pacman -Qkk`. The
installed `/usr/bin/ffmpeg-n1x` SHA256 is the exact extracted binary hash
`9e0a2fe0939faac9cfbc440a179d7deb5bafd3c1c781411f77092cb81f171314`;
installed `/usr/bin/ffplay-n1x` SHA256
`ec0ac9067baa2692340b089cf28cbaa9d70f67ca5c51b399c25a9cafef3a40ac`
also matches the extracted player from the timed test. The
[installed Spline36 repeat](libplacebo-upscale-installed-package7-kernel38.json)
processes 60 distinct GPU frames against libplacebo API 360 with the same
33.78 dB Y PSNR and 0.96023 SSIM. CPU bicubic still scores 35.68 dB and
0.96887 on this fixture, so no quality-based default filter change follows.
Normal export-application color tagging, human visual review, steady latency
and post-resume use remain open.
