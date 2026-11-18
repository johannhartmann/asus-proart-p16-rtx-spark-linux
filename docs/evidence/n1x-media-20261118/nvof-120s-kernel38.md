# Native kernel38 120-second NVOFA test

On the first native `7.2.8-38-rtx-spark-npu` boot (boot ID
`806fab11-2c93-426d-805b-8a82426047b8`), the installed
`p16-nvof-tools 0.1.0-4` recorded the internal RGB camera at 1280×720/30
for a requested 120 seconds, then exported with NVOFA and Vulkan H.264.
The [machine-readable result](nvof-120s-kernel38.json) records 122.171 seconds
of recording wall time and 197.201 seconds of export time. Temporary camera
footage was deleted.

The source had **3,585** frames between PTS 0 and 119.967 seconds. Its decoded
frame timestamps show **15** gaps of 66–67 ms, each accounting for one
nominal 30-fps frame. The gaps include the first at 2.133 s and several
roughly 4.5–4.7 seconds apart; no timestamp reversal occurred. This proves
the shortfall is present in the encoded source timeline; it does not yet
attribute the cause to the sensor, USB/V4L2, recorder or encoder queue.

NVOFA processed every available adjacent pair and exported
**7,169 = 2 × 3,585 − 1** decodable H.264 frames at 1280×720/60. The strict
3,600-source-frame gate failed. No DMA-debug mapping warning, kernel BUG,
KASAN report, NVIDIA Xid or IOMMU fault appeared in this native test window.
The kernel38 UVC allocation fix is independently qualified by the
[RGB/IR DMA gate](../kernel38-native-20261118.md); this longer cadence issue
remains open.
