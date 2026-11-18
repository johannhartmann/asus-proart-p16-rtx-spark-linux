# P16 internal OLED HDR10 application output

18 November 2026; ASUS ProArt P16 H7607BA, Samsung `ATNA60HC05-0`,
NVIDIA 615.78.08, Hyprland 0.57.0, mpv 0.41.0, `p16-media-tools 0.1.0-2`.
Package archive SHA256:
`517134eec1a88510748e0fed72c1c3c94f757ec166424256dc1dc98a6b3e18ed`.
The installed `/usr/bin/p16-hdr-play` SHA256 matches the source:
`291aea39c5ed3cadba150bfe09a2f42f60290e6f959518611f312e8aa942d92e`.

`edid-decode` of the NVIDIA DRM connector's EDID reports BT.2020 RGB,
SMPTE ST2084/PQ, HDR Static Metadata Type 1, 1600 cd/m² desired peak,
702.5 cd/m² frame-average maximum and 12 bpc native OLED depth. These are
EDID claims, not measured luminance or accuracy. The attached Samsung U28E590
has no HDR EDID block. Raw EDID is omitted because it contains device IDs.

The included [`hdr10-hevc.hevc`](hdr10-hevc.hevc) is a 120-frame 640×360 HEVC
Main10 fixture (SHA256 `787c282c3161defa8f169a5418fbf83531050a8b773fff8ae23440a8877fffe8`).
It was made from FFmpeg `testsrc2` raw `yuv420p10le` with the local x265 4.3
10-bit build using `--video-signal-type-preset BT2100_PQ_YCC`, HDR10 mastering
display metadata `G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,5)`
and `--max-cll 1000,400`. FFprobe reports `bt2020nc`, `smpte2084`, `bt2020`.
The synthetic pixel values were not calibrated as a visual HDR test pattern.

Reproduce on the reference P16:

```sh
python3 scripts/check-p16-hdr-output.py \
  docs/evidence/n1x-media-20261118/hdr10-hevc.hevc \
  /tmp/p16-hdr-output.json
```

[`hdr-output.json`](hdr-output.json) records state before, during and after
installed `p16-hdr-play` playback. During playback, mpv selected Vulkan
hardware decoding, `vulkan[p010]`, PQ/BT.2020 Wayland color and the
`VK_COLOR_SPACE_HDR10_ST2084_EXT` 10-bit Vulkan surface. Hyprland switched
the internal output from `XRGB8888/srgb` to `XBGR2101010/hdr`. NVIDIA DRM
switched eDP-1 from Colorspace 0 to BT2020_RGB 9 and transmitted nonzero
HDR_OUTPUT_METADATA. On normal mpv exit, the display returned to its prior
SDR mode, Colorspace 0 and zero metadata. The full selected mpv output is
[`hdr-output.mpv.log.gz`](hdr-output.mpv.log.gz); the launcher output is
[`hdr-output.launcher.log.gz`](hdr-output.launcher.log.gz).

[`hdr-watchdog.json`](hdr-watchdog.json) records a separate run: the launcher
was killed with SIGKILL while HDR output and mpv were active. Its independent
watchdog terminated mpv and reloaded Hyprland; the monitor returned to SDR,
DRM Colorspace 0 and zero metadata. No Hyprland configuration error remained.
No persistent `~/.config/hypr` setting was changed.

This establishes one Linux application HDR10 output path on the internal
panel. It does not measure physical luminance, color accuracy, tone mapping
quality or latency, and it does not implement SDR-to-HDR conversion or
NVIDIA's proprietary TrueHDR effect. The raw HEVC fixture has no timestamps;
A/V sync is not part of this test.
