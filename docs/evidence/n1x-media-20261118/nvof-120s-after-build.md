# 120-second NVOFA capture after kernel compilation

The same installed `p16-nvof-tools 0.1.0-4` soak gate was repeated after the
kernel38 compilation ended, on the kernel37 boot with the temporary UVC DMA
candidate still loaded. The capture occupied 122.309 seconds of wall time for
the requested 120 seconds. A short driver-package reinstall overlapped the
beginning of capture, so this is mostly idle operation, not a fully controlled
idle benchmark.

The camera supplied **3,586 of 3,600** requested 1280×720/30 frames. The
NVOFA/Vulkan pipeline processed every captured adjacent pair and exported
**7,171 = 2 × 3,586 − 1** H.264 frames at 1280×720/60. Independent FFmpeg
decoding passed. The 198.692-second export overlapped the kernel38 UKI rebuild
after recording ended. No camera pixels were retained. The [machine-readable
result](nvof-120s-after-build.json) has the exact measurements.

The strict capture-cadence gate failed again, this time by 14 frames. The
successful 20-second/600-frame test and both 120-second results show that
interpolation accounts for all frames it receives, but do not establish
uninterrupted 30 fps input over two minutes. A native kernel38 repeat and
frame-timestamp/drop analysis are needed before treating long-running camera
capture as qualified.
