# N1X H.264 encoder for Chrome WebRTC

This is an opt-in user-space VA-API driver for the P16's NVIDIA Vulkan Video
H.264 encoder. It is based on
[`imperishableSecret/vulkan-video-vaapi` `h264-encode-vulkan` at `18d4c427`](https://github.com/imperishableSecret/vulkan-video-vaapi/tree/18d4c427d01a59ad51be9f28435948567a709ace)
with [the local patch](0001-n1x-chrome-h264-baseline-cbr.patch). The patch
adds H.264 Constrained Baseline, CBR mapping, persistent VA rate parameters,
and a `vaDeriveImage` writeback path for Chrome's shared-memory frames. Encode
is only advertised when the Vulkan device reports H.264 encode and CBR support
and `VKVV_ENABLE_ENCODE=1` is set.

The patch uses a temporary CPU-visible VA image for Chrome's upload. It is an
application-compatible staging path, not zero-copy capture. The upstream driver
is experimental; this integration does not replace the installed NVIDIA
NVDEC-backed VA-API driver or change the running kernel or NVIDIA driver.

## Build and install for this user

Dependencies: `git`, `meson`, `ninja`, `pkg-config`, the `libva`, `libva-drm`,
`libdrm`, Vulkan loader and headers, and GStreamer codecparsers development
files. On this machine Vulkan headers are available in the extracted signed
package at `/home/johann/p16/video-build/vulkan-headers-1.4.363/usr/include`:

```bash
VULKAN_HEADER_DIR=/home/johann/p16/video-build/vulkan-headers-1.4.363/usr/include \
  platform/video/vaapi-h264/build-install-user
platform/video/vaapi-h264/install-launcher-user
```

The build script pins the upstream commit, applies the patch, builds the
driver, runs all 22 upstream smoke tests, and installs
`~/.local/lib/p16-vaapi-h264/nvidia_vulkan_drv_video.so`. It aborts if the
upstream branch has moved. If `/usr/include/vulkan/vulkan.h` is installed,
`VULKAN_HEADER_DIR` can be omitted. `P16_VAAPI_DRIVER_DIR` changes the user
installation directory for the driver and launcher. `install-launcher-user`
installs the Meet-only codec gate and launcher under the user's home directory;
`P16_MEET_SUPPORT_DIR` changes their installation directory.

## Use and verify

```bash
p16-meet-chrome
node scripts/check-browser-encode.mjs /tmp/p16-webrtc-encode.json \
  --profile=baseline \
  --driver-path="$HOME/.local/lib/p16-vaapi-h264"
```

`p16-meet-chrome` uses a dedicated Chrome profile at
`${XDG_DATA_HOME:-$HOME/.local/share}/p16-meet-chrome`. Sign into Meet there.
`P16_MEET_CHROME_PROFILE` can choose a different profile. A running ordinary
Chrome process cannot acquire the new VA-API library or flags without a restart;
the dedicated profile prevents Chrome from silently reusing that process.

The launcher loads a [Meet-only H.264 codec gate](meet-h264-codec/codec-gate.js)
before opening the site. It calls the standard WebRTC
`RTCRtpTransceiver.setCodecPreferences()` API for video-sending transceivers,
offering H.264 with retransmission and error repair. Receive-only transceivers
keep their original codecs. The gate leaves negotiation alone if Chrome does
not advertise H.264. The remote peer must still accept H.264 and the requested
stream must be supported by the hardware encoder. The extension only runs on
`meet.google.com` in this dedicated profile.

Google Chrome 137+ ignores the `--load-extension` flag. The launcher uses a
local DevTools pipe to load the unpacked extension before Meet opens and keeps
that pipe open for the browser session. It exposes no debugging TCP port.
Closing the dedicated Chrome window ends the launcher. Close an older
`p16-meet-chrome` instance once before starting this version.

The WebRTC test uses two local peers with a generated 640×360 canvas stream,
prefers H.264 Constrained Baseline and checks browser outbound/inbound stats
plus actual Vulkan encode submissions. It exercises Chrome/WebRTC, not Google
Meet. The [installed-driver result](../../../docs/evidence/n1x-media-20261120/chrome-vulkan-vaapi-h264-baseline.json)
recorded 151 encoded, sent, received and decoded frames, 151 Vulkan H.264
submissions, and zero Chrome encoder errors. `encoderImplementation` was not
present in Chrome's outbound stats, so the driver submissions are the direct
hardware-path evidence. Do not infer a Meet performance gain from this local
loopback result.

The [codec-gate local test](../../../docs/evidence/n1x-media-20261120/chrome-meet-h264-codec-gate.md)
omitted the page's explicit H.264 preference. The gate selected H.264
Constrained Baseline; Chrome sent and received 148 frames with 148 Vulkan
encode submissions and zero browser encoder errors. A separate branded-Chrome
launcher test confirmed that the extension was active before a page loaded.

In a real Meet call, check `chrome://webrtc-internals` for the outbound codec,
frame count and encode time; H.264 must be negotiated for this driver to be
used. The [first live check without the codec gate](../../../docs/evidence/n1x-media-20261120/chrome-live-meet-vulkan-vaapi.md)
joined Meet with this profile and observed an active AV1 stream using the
software `libaom` encoder. The bridge loaded, but Meet did not select H.264.
Compare CPU load with the same resolution, effects and participants in
ordinary Chrome and this isolated profile only after hardware encode is
actually selected. Meet may negotiate VP8, VP9 or AV1, for which this
H.264-only driver does not provide encode. Camera decode and Meet's effects
remain separate CPU costs.

No reboot is required. To roll back, close the dedicated Chrome window and use
ordinary Chrome. Remove `~/.local/bin/p16-meet-chrome`,
`~/.local/share/p16-meet-support`, and
`~/.local/lib/p16-vaapi-h264/nvidia_vulkan_drv_video.so` to uninstall this
user-local integration.
