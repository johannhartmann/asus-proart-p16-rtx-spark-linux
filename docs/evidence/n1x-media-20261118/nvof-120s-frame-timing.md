# 120-second NVOFA capture with decoded frame timing

The installed `p16-nvof-tools 0.1.0-4` repeated the live P16 RGB camera
1280×720/30 recording on the kernel37 boot with the temporary UVC DMA
candidate. This run followed the earlier kernel builds and did not overlap a
package installation or kernel compilation. The [result](nvof-120s-frame-timing.json)
records 122.194 seconds of recording wall time for a requested 120-second
file and 197.622 seconds for NVOFA/Vulkan export.

The source contained **3,596** frames, timestamped from 0 to 119.967 seconds.
Decoded frame timestamps had two gaps over 50 ms: **67 ms** after frame 1368
at 45.600 s, and **134 ms** after frame 1710 at 57.033 s. Relative to the
nominal 33.3 ms interval, these account for one and three missing camera
frames respectively. There were no nonpositive timestamp gaps. This explains
the four-frame shortfall in this run more precisely than the previous two
120-second tests, but does not establish whether the gaps arose in the camera,
USB transport, V4L2 queue or recorder scheduling.

NVOFA processed every available adjacent pair, and Vulkan exported
**7,191 = 2 × 3,596 − 1** decodable H.264 frames at 1280×720/60. No new
DMA-debug, IOMMU, NVIDIA Xid, KASAN, BUG or WARNING line appeared during the
run. The exact 3,600-frame input gate remains failed. Temporary camera
footage was deleted. Repeat on native kernel38, then inspect live USB/V4L2
timing if the gaps recur before claiming two-minute 30-fps capture quality.
