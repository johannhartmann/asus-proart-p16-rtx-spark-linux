# Google Chrome VA-API playback on N1X

On 18 November 2026, Google Chrome 156.0.8078.79 on the P16 decoded the
generated H.264 1280×720/24 fps fixture through `VaapiVideoDecoder` with
`kIsPlatformVideoDecoder=true`. CDP Media reported all 96 frames over four
seconds and zero dropped frames in the [minimal-flag run](browser-decode-chrome-simple-720p.json).
The [P16 launcher source run](browser-decode-p16-wrapper-720p.json) and
[installed package run](browser-decode-p16-installed-720p.json) also selected
`VaapiVideoDecoder` for all 96 frames. The launcher sets
`LIBVA_DRIVER_NAME=nvidia`, `NVD_BACKEND=direct`, ANGLE/GL and NVIDIA VA-API
feature flags, and uses an independent Chrome profile so an existing Chrome
process cannot absorb the command without applying its flags.

The earlier [320×180 Chrome run](browser-decode-google-chrome.json) used the
same core flags and selected `FFmpegVideoDecoder`. That source size was too
small to establish the hardware path. Increasing it to 1280×720 with otherwise
the same flags selected VA-API. Arch ARM Chromium 156.0.8078.73 continued to
select `FFmpegVideoDecoder` at 1280×720, both with the
[core flags](browser-decode-nvidia-720p.json) and with
[additional VA-API switches](browser-decode-nvidia-advanced-720p.json).
Those are explicit software fallback controls, not decode failures.

The driver is `libva-nvidia-driver` 0.0.18-1 on NVIDIA 615.78.08.
[Chromium's VA-API documentation](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/gpu/vaapi.md)
describes the NVIDIA and ANGLE flags and warns that NVIDIA VA-API support is
experimental in Chromium. The
[driver's Chrome guidance](https://github.com/elFarto/nvidia-vaapi-driver#chrome)
lists the same core flags. The extended Chrome flags tested here did not
improve on the core set. Chromium's
[media switches source](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/media/base/media_switches.cc)
has a minimum-resolution performance gate; this machine's 320×180 versus
1280×720 result is consistent with such a gate, without proving which check
rejected the small stream.

The installed package is `p16-media-tools` 0.1.0-4, archive SHA256
`0e3bbd55a8d5d6b15f607cd45add9b1438ec1f420b4e39722897f1e91b0efa7a`.
`pacman -Qk` reports 14 files with none missing; `/usr/bin/p16-video-chrome`
has the same SHA256 as the repository script,
`9d2f74b2350d393666684467da9f8d17efd597da3da15ee8b0ecbcdf65b87099`.
A [libva API trace summary](browser-decode-p16-libva-trace.json) from the
installed run records one VA context, 96 successful `vaBeginPicture` and
`vaRenderPicture` calls, 95 successful `vaEndPicture` calls and 21 successful
surface exports, with no libva error returns. The raw trace was deleted after
counting. This independently confirms that Chrome invoked the VA-API driver;
the 95 completions do not establish a one-to-one match with the 96 DOM frames.
Qualification covers only this H.264 fixture in a test Chrome profile.
Different codecs, web sites, resolutions, continuous use and resume need
separate application tests. No independent GPU engine counter was recorded
during this four-second run.
