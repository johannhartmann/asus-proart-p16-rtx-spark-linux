# N1X Optical Flow midpoint video export candidate

18 November 2026; ASUS ProArt P16 H7607BA, NVIDIA 615.78.08, distribution
FFmpeg 9.0.2-2, CUDA 13.4.2, mpv 0.41.0. Package candidate
`p16-nvof-tools 0.1.0-3` was built with pinned Optical Flow SDK headers;
archive SHA256:
`ecda4eaf4aee77ebf05ad79ad02cad9002fe28ca1283e4fc307c800f56fd1875`.
The candidate analyzer and source wrapper were tested before installation.
The installed package remained `0.1.0-1` while graphical authentication was
pending. [`nvof-interpolation.json`](nvof-interpolation.json) identifies the
tested binaries by SHA256; it does not claim the candidate was installed.

The candidate's `p16-interpolate-video` decodes frames with FFmpeg and
computes forward and backward motion vectors with the N1X Optical Flow
Accelerator. It warps and blends adjacent 320×180 RGB frames on the CPU to
make one temporal midpoint, then encodes at twice the source frame rate with
NVIDIA Vulkan Video H.264. Input audio is copied and trimmed to the output.
This is a Linux Optical Flow API and Vulkan Video application path, not
NVIDIA's proprietary RTX Video Frame Generation SDK.

The deterministic random-texture control translates a frame eight pixels.
The original first and last frames were preserved. In the interior image
region, the midpoint matches the exact four-pixel ground truth with MSE 0;
plain crossfading gives MSE 8239.18. This checks direction, warp, and output
frame count for one well-behaved translation. It does not represent occlusion,
complex motion, or visual acceptance of camera footage.

The timed A/V test exported 48 input video frames at 24 fps to 95 H.264
frames at 48 fps, retained AAC audio and ended the video and audio tracks
within 16 ms. Independent FFmpeg decoding succeeded. The real P16 RGB camera
test recorded 60 H.264 frames at 30 fps, exported 119 frames at 60 fps, and
independently decoded the result. The exported clip played to EOF in the
installed mpv command with VA-API hardware decode and Vulkan/libplacebo
rendering. [`nvof-interpolation-camera.log`](nvof-interpolation-camera.log)
records NVOFA pair execution and the Vulkan Video encoder; temporary camera
pixels and output clips were deleted.

Candidate reproduction:

```sh
python3 scripts/check-p16-nvof-interpolation.py \
  docs/evidence/n1x-media-20261118 \
  --analyzer /path/to/candidate/p16-nvof-analyze \
  --wrapper platform/video/nvof/p16-interpolate-video
```

The installed package needs the same test without path overrides before the
export can be marked installed and used. Current output is limited to
320×180, uses CPU warping, and has no perceptual motion-artifact review or
long-playback qualification. Variable-frame-rate input is untested and the
wrapper assumes a constant frame rate. The measured A/V timestamp bound
applies only to the two-second fixture.
