# HEVC RExt 12-bit VA-API pixel readback on kernel38

The [repeatable checker](../../../scripts/check-hevc12-vaapi-readback.py)
generates a 30-frame, 320×180 HEVC RExt 4:2:0 **12-bit** fixture with the
local 12-bit x265 build. `ffprobe` confirms `profile=Rext` and
`pix_fmt=yuv420p12le` before decoding. The checker decodes it through FFmpeg
software and through the installed NVIDIA VA-API direct backend, downloads
the hardware surfaces as `p012le`, and compares all 5,184,000 output bytes.
The synthetic input and raw outputs are deleted after hashing. The
[machine-readable result](hevc12-vaapi-readback-kernel38.json) pins their
hashes, exact machine stack and selected backend.

On native `7.2.8-38-rtx-spark-npu` with NVIDIA `615.78.08`,
`libva-nvidia-driver 0.0.18-1` and distribution FFmpeg `9.0.2-2`, **30/30**
VA-API frames were downloaded with `-threads 1`. Their `p012le` SHA256 is
byte-identical to the software decode. The FFmpeg log selected
`VA-API NVDEC driver [direct backend]`, exposed `vaapi` surfaces, and reported
zero decode errors. This qualifies 12-bit 4:2:0 pixel readback for the
bounded, single-decoder-thread path.

Without `-threads 1`, an equivalent 30-frame readback made no progress after
seven output frames and reached a 30-second test timeout; enlarging the
hardware-frame pool to 16 made no progress after two frames in a 15-second
test. A one-frame readback succeeded. Those observations suggest a
thread/surface-lifetime interaction, but do not identify its owner. The
timed-out FFmpeg processes were terminated; NVIDIA remained responsive and
the kernel logged no new GPU or IOMMU warning. The initial exploratory
timeout used a 10-bit x265 binary by mistake and is excluded from the
12-bit result above.

The `-threads 1` workaround is explicit in the checker. Default-thread
readback, 4:4:4 preservation, sustained playback and post-resume readback
remain open.
