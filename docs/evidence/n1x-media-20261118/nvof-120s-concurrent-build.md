# NVOFA live-camera stress during kernel compilation

On kernel `7.2.8-37-rtx-spark-npu` with NVIDIA 615.78.08, the installed
`p16-nvof-tools 0.1.0-4` recorded the P16 RGB camera through the temporarily
loaded UVC DMA-limit candidate and Vulkan Video H.264 while the kernel38
package compiled with eight jobs. This was deliberately a concurrent-load
test, not a controlled performance benchmark. The [machine-readable result](nvof-120s-concurrent-build.json)
contains the frame and elapsed-time counts; the temporary camera recordings
were deleted.

The requested 120-second 1280×720/30 capture returned 3,592 frames rather
than the 3,600 required by the test. The source recording took 122.417 seconds
wall time. NVOFA analyzed all 3,591 adjacent pairs; the Vulkan H.264 export
contained the expected `2 × 3,592 − 1 = 7,183` frames at 1280×720/60 and
decoded independently without error. The export took 204.914 seconds.

The test exits **1** because its exact input-frame gate failed by eight
frames. This does not establish whether the shortfall came from camera timing,
capture scheduling or the concurrent build. The kernel log had no new
`DMA-API`, `WARNING`, `BUG`, `KASAN` or NVIDIA Xid line in the test window.
Repeat the same 120-second case without build load before claiming long-run
capture cadence or throughput. The export correctness result is narrower than
that cadence gate.
