# Default Chrome launcher for N1X Meet H.264

The ordinary Omarchy Chrome desktop IDs point at the user-installed P16
launcher. The launcher keeps the default Chrome data directory and starts
the browser with the Vulkan Video VA-API driver. Chrome 156 uses its
documented Linux external CRX loader to install the Meet extension. The
ordinary profile needs no debug flags, separate login or system reboot.

## Isolated verification

Google Chrome 156.0.8078.79 on the ASUS ProArt P16 N1X with NVIDIA 615.78.08.
The headless WebRTC test used the regular launcher implementation and a
fresh Chrome profile. It let Chrome install the signed CRX, served a local
canvas test at the extension's Meet origin using a request interception,
and let the installed extension set codec preferences before negotiation.
No page-level codec preference or injected test script set the codec.

| Observation | Result |
| --- | --- |
| Chrome's external extension discovery | Installed automatically |
| Extension codec preference calls | 3 successful, 0 errors |
| Negotiated codec | H.264 Constrained Baseline, `42e01f` |
| Video size | 640 × 360 |
| Frames encoded, sent and received | 151 each |
| Frames decoded at sampling time | 147 |
| Vulkan H.264 submissions | 151 |
| Chrome encoder errors | 0 |

Both generated desktop files passed `desktop-file-validate`. Omarchy
continued to resolve `google-chrome.desktop`, whose user entry now points at
the P16 launcher.

A separate headless H.264 playback fixture at 1280 × 720 completed all
72 frames with zero drops. Chrome reported `FFmpegVideoDecoder` and
`kIsPlatformVideoDecoder=false`. This run verifies playback and leaves
hardware decoding through the new launcher unqualified.

## Real Meet call

Qualification requires a new call in the regular signed-in profile after
Chrome restarts. Record an active outbound H.264 stream and hardware
submissions before attributing a CPU or power change to the encoder. Compare
matching camera resolution, participant count and effects against a software
run. The isolated test does not measure Meet's negotiation or CPU use.
