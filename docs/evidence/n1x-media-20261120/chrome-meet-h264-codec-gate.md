# Meet H.264 codec gate, 20 November 2026

## Why

The [first live Meet check](chrome-live-meet-vulkan-vaapi.md) used AV1 with the
software `libaom` encoder despite the H.264 Vulkan Video VA-API bridge being
loaded. The bridge can only help if the WebRTC video sender negotiates H.264.

## Implementation

`platform/video/vaapi-h264/meet-h264-codec` is a Manifest V3 content script
restricted to `https://meet.google.com/*`. It runs in the page's main world at
`document_start` and uses
[`RTCRtpTransceiver.setCodecPreferences()`](https://developer.mozilla.org/en-US/docs/Web/API/RTCRtpTransceiver/setCodecPreferences)
to restrict video-sending transceivers to Chrome's own H.264 capabilities plus
repair codecs. Receive-only transceivers keep their original codec list. It
does not rewrite SDP, affect ordinary Chrome, or claim support for another
codec in the VA-API driver.

The user-local `p16-meet-chrome` launcher starts branded Chrome with the same
VA-API flags as the proven H.264 loopback path, opens a local DevTools pipe,
loads the extension before creating the Meet tab, and keeps the pipe open.
Chrome 137+ [ignores `--load-extension` in branded builds](https://groups.google.com/a/chromium.org/g/chromium-extensions/c/1-g8EFx2BBY/m/S0ET5wPjCAAJ).
The pipe uses file descriptors 3 and 4; no debugging TCP port is opened. The
[CDP `Extensions.loadUnpacked` method](https://chromedevtools.github.io/devtools-protocol/tot/Extensions/#method-loadUnpacked)
requires `--enable-unsafe-extension-debugging`. A one-shot load did not persist
on restart, so the launcher holds the pipe for the browser session.

## Local checks

On Google Chrome 156.0.8078.79, kernel `7.2.8-38-rtx-spark-npu`, NVIDIA
615.78.08:

```bash
node scripts/check-browser-encode.mjs /tmp/p16-meet-h264-gate-v2-test.json \
  --profile=baseline \
  --driver-path="$HOME/.local/lib/p16-vaapi-h264" \
  --gate="$PWD/platform/video/vaapi-h264/meet-h264-codec/codec-gate.js"
```

This check made a local WebRTC sender and receiver without asking the page to
prefer H.264. The codec gate recorded three successful preference applications
and zero errors. The selected RTP codec was H.264 with
`profile-level-id=42e01f`, and Chrome reported 148 encoded, 148 sent, 148
received, and 147 decoded 640×360 frames. The VA-API driver's log contained 148
H.264 Vulkan encode submissions; Chrome reported zero encoder errors. The
[short result JSON](chrome-meet-h264-codec-gate.json) records these values.

A separate branded-Chrome launcher check used a temporary extension manifest
that additionally matched `127.0.0.1`. The local page displayed `H264 GATE
ACTIVE` on first load after `Extensions.loadUnpacked`, proving the launcher
activates the extension before navigation. The shipped manifest still matches
Meet only. The installed user launcher and support files are in `~/.local/bin`
and `~/.local/share/p16-meet-support`.

## Live qualification

The previously used meeting later refused new joins. A second active room
supplied for this check immediately showed `You can't join this video call` in
the dedicated profile before any WebRTC outbound stream was established. A
fresh Chrome control profile **without** the extension showed the same error
for that room, while the normal signed-in Chrome was in the meeting. Thus the
gate did not cause the refusal. The precise Meet access rule was not exposed;
the separate profile was unsigned-in. No live hardware encode or CPU/power
improvement is claimed. Once this profile can enter the room, inspect
`chrome://webrtc-internals` for the active outbound codec and encoder, then
correlate its frames with Vulkan encode submissions and compare CPU/power at
matched resolution and participant count.
