# N1X Optical Flow midpoint video export

18 November 2026; ASUS ProArt P16 H7607BA, NVIDIA 615.78.08, distribution
FFmpeg 9.0.2-2, CUDA 13.4.2, mpv 0.41.0. Installed package
`p16-nvof-tools 0.1.0-4` was built with pinned Optical Flow SDK headers;
archive SHA256:
`48ce9acd470864e94586a8ec93abc4239f8b9394eefe2800396566680a5ffcc9`.
The final test used both commands from `/usr/bin` after installation.
[`nvof-interpolation.json`](nvof-interpolation.json) identifies their SHA256
hashes, matching the package archive.

The installed `p16-interpolate-video` decodes frames with FFmpeg and
computes forward and backward motion vectors with the N1X Optical Flow
Accelerator. It warps and blends adjacent RGB frames at source resolution on
the CPU to make one temporal midpoint, then encodes at twice the source frame
rate with
NVIDIA Vulkan Video H.264. Input audio is copied and trimmed to the output.
This is a Linux Optical Flow API and Vulkan Video application path, not
NVIDIA's proprietary RTX Video Frame Generation SDK.

The deterministic random-texture control translates a frame eight pixels.
The original first and last frames were preserved. In the interior image
region, the midpoint matches the exact four-pixel ground truth with MSE 0;
plain crossfading gives MSE 8239.18. This checks direction, warp, and output
frame count for one well-behaved translation. It does not represent occlusion,
complex motion, or visual acceptance of camera footage. A second 1280×720
translation control produced three frames and sampled midpoint MSE 0.

A separate [occlusion fixture](nvof-occlusion.json) moves a 48×48 foreground
with a unique, nonperiodic texture 16 pixels across an independently textured
stationary background. The known midpoint is 8 pixels between the endpoints.
On a region containing the moving object and exposed background, NVOFA
midpoint MSE is 783 versus 2195 for a direct crossfade. Around the leading
and trailing exposure boundaries, local MSE remains around 2008–2663; static
background MSE is about 26. This supports a real improvement over crossfade
on a controlled occlusion, while showing visible-edge error remains possible.
An earlier periodic checkerboard control was discarded because identical
patterns at multiple offsets made the correspondence ambiguous.

The timed A/V test exported 48 input video frames at 24 fps to 95 H.264
frames at 48 fps, retained AAC audio and ended the video and audio tracks
within 16 ms. Independent FFmpeg decoding succeeded. The real P16 RGB camera
test recorded 60 H.264 1280×720 frames at 30 fps, exported 119 frames at
1280×720/60 fps, and independently decoded the result. The exported clip
played to EOF in the
installed mpv command with VA-API hardware decode and Vulkan/libplacebo
rendering. [`nvof-interpolation-camera.log`](nvof-interpolation-camera.log)
records NVOFA pair execution and the Vulkan Video encoder; temporary camera
pixels and output clips were deleted.

Reproduce on the reference P16:

```sh
python3 scripts/check-p16-nvof-interpolation.py \
  docs/evidence/n1x-media-20261118
```

The source-resolution export is installed and was consumed by a real camera
clip and a normal desktop player. The two-second camera export took about
5.2 seconds on this machine. Current output uses CPU warping and has no
perceptual motion-artifact review or long-playback qualification.
Variable-frame-rate input is untested and the
wrapper assumes a constant frame rate. The measured A/V timestamp bound
applies only to the two-second fixture.
