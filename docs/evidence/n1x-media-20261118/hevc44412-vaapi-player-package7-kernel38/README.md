# Extracted 9.0.2-7 FFplay regression

[`hevc44412-vaapi-playback.json`](hevc44412-vaapi-playback.json) compares the
installed 9.0.2-5 player and the extracted 9.0.2-7 package player on one
30-frame, 10 fps HEVC RExt 4:4:4 12-bit Matroska fixture. CUVID and VA-API
decode each reach EOF through the libplacebo/Vulkan renderer in both players;
the raw logs record decoder selection, renderer input and clock progress.

An earlier run stalled on both binaries while both displays had DPMS off.
The harness now checks display power before running. The retained result is
the passing run with DPMS on. The Omarchy screensaver stayed locked; no
desktop configuration or boot state changed. The package is still extracted
only, so installed-package regression remains open.
