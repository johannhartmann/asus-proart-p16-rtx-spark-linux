# N1X Optical Flow Accelerator in a Linux video workflow

18 November 2026; ASUS ProArt P16 H7607BA, kernel
`7.2.8-36-rtx-spark-npu`, NVIDIA 615.78.08, CUDA 13.4.2.

The installed `p16-nvof-tools 0.1.0-4` package was built from
[`platform/video/nvof/PKGBUILD`](../../../platform/video/nvof/PKGBUILD).
Its NVIDIA Optical Flow SDK 2.0 headers are pinned to commit
`edb50da3cf849840d680249aa6dbef248ebce2ca` with SHA256 checksums.
The package archive SHA256 is
`48ce9acd470864e94586a8ec93abc4239f8b9394eefe2800396566680a5ffcc9`.
The installed analyzer SHA256 is
`a681396d3aeef2a18bb3e872975b7ac14de13ce01a54826aed282881cfdb71ac`.
This revision buffers JSON until a complete frame pair succeeds and includes
the separately tested midpoint video export command.

The direct API probe established `NvOFAPICreateInstanceCuda`, CUDA context,
NVOFA handle, supported output grids 1/2/4, session initialization, buffer
allocation, `nvOFExecute`, synchronization and readback on this device. The
driver reports maximum Optical Flow API version 5.0 and accepts the pinned
2.0 client API. The packaged command uses 4×4 output cells and signed S10.5
flow vectors. [`nvof-application.json`](nvof-application.json) records the
installed test. It uses two deterministic 320×180 random-texture frames as a
zero-motion control, then translates the second frame eight pixels right:

| Input pair | Mean horizontal flow | Mean magnitude |
| --- | ---: | ---: |
| Identical | approximately 0 px | 0.0002 px |
| 8 px horizontal translation | 8.0000 px | approximately 8 px |

The application test then used `p16-record-camera-vulkan` to make a temporary
two-second H.264 1280×720/30 recording from the real internal P16 RGB camera.
`p16-optical-flow CAMERA.mkv 30` decoded and resized that video with the
distribution FFmpeg, submitted 30 adjacent frame pairs to NVOFA and returned
per-pair motion vectors. The measured mean magnitude was above zero. The
recording had 60 independently probed frames; it and its image pixels were
deleted after analysis. The [recording log](nvof-camera-record.log) replaces
its temporary directory with `$TEMP`.

Reproduce the bounded check on the reference P16:

```sh
python3 scripts/check-p16-optical-flow.py docs/evidence/n1x-media-20261118
```

This qualifies an actual optical-flow computation and a packaged video
analysis command on Linux ARM64. Midpoint export and bounded A/V are tested
separately in [the interpolation record](nvof-interpolation.md); neither test
establishes perceptual motion-artifact quality or NVIDIA's proprietary RTX
Video Frame Generation application feature.
