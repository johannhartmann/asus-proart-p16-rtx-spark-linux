# P16 Optical Flow

`p16-optical-flow VIDEO [MAX_PAIRS]` decodes a local video through FFmpeg,
resizes it to 320×180 grayscale, and submits successive frames to the N1X's
NVIDIA Optical Flow Accelerator through the published CUDA Optical Flow API.
It prints JSON with per-pair mean motion vectors, mean magnitude and the share
of vectors moving at least half a pixel. The default is 30 frame pairs; the
maximum is 300. It does not retain source pixels or write a video.

The engine uses 4×4 output cells, S10.5 signed flow vectors and NVIDIA's
Optical Flow SDK 2.0 headers pinned to commit
`edb50da3cf849840d680249aa6dbef248ebce2ca`. The installed N1X driver
reports a maximum API version of 5.0. This package uses the older published
2.0 interface to maintain a fully auditable userspace build. Successful handle
creation, initialization and execution were verified separately. The JSON
output is a motion-analysis result.

`p16-interpolate-video INPUT_VIDEO OUTPUT.mkv [MAX_FRAME_PAIRS]` uses NVOFA
vectors in both directions to warp neighboring 320×180 RGB frames to their
temporal midpoint. It exports one midpoint per source pair with FFmpeg's
NVIDIA Vulkan Video H.264 encoder, doubling the source frame rate. When the
input has audio, it copies the track to the output and trims it to the video.
The default processes the full file up to one million frame pairs; pass a
smaller bound for a short export. The command requires a usable constant input
frame rate, refuses to overwrite existing files and discards partial output
on failure. The implementation uses CPU warping after dedicated hardware flow
computation. Its current 320×180 output is an experimental baseline, not a
production-quality high-resolution interpolator or NVIDIA RTX Frame Generation.

Run `p16-optical-flow camera.mkv 30 > flow.json` on a video file. Both a
controlled eight-pixel translation and a short real P16 camera recording were
used to qualify the installed command. The midpoint export has its own
controlled-image, timed A/V and live-camera tests in the
[media evidence](../../../docs/evidence/n1x-media-20261118/README.md).
