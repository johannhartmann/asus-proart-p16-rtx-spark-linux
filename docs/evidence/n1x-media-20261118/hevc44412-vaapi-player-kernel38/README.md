# Timed HEVC 4:4:4 12-bit application playback

Run `scripts/check-hevc44412-vaapi-playback.py` with the pinned x265 12-bit
binary, installed `/usr/bin/ffplay-n1x`, and the extracted 9.0.2-6 package
binary. The script creates a 30-frame HEVC RExt `yuv444p12le` fixture, assigns
continuous 10 fps packet timestamps, checks the Matroska stream, plays it
through CUVID and VA-API with FFplay's libplacebo/Vulkan renderer, then
discards the temporary source and video files. The four raw player logs and
[`hevc44412-vaapi-playback.json`](hevc44412-vaapi-playback.json) retain the
backend selection, renderer input, video clock and EOF checks.

All four paths passed on kernel 7.2.8-38 with NVIDIA 615.78.08. VA-API used
the NVIDIA direct backend and delivered `vaapi` frames to the FFplay render
stage. The installed 9.0.2-5 player passed too. Thus the Q416 patch in
9.0.2-6 is needed for FFmpeg's correct 16-bit CPU readback, rather than for
this particular FFplay playback route. The logs do not prove zero-copy from
NVDEC to display, physical display depth, or color accuracy. The 9.0.2-6
package is still awaiting installation and an installed-package regression.
