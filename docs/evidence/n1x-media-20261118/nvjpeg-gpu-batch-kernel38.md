# nvJPEG GPU-compute decode on native kernel38

The [reproducible test](../../../scripts/check-nvjpeg-gpu-batch.py) generates a
320×180 baseline 4:2:0 JPEG from FFmpeg `testsrc2`, compiles the pinned
[`nvJPEG` probe](../../../scripts/probe-nvjpeg-gpu-batch.c), and decodes a
64-image batch through `NVJPEG_BACKEND_GPU_HYBRID` into CUDA device memory.
The installed CUDA headers document GPU-assisted Huffman decoding for
baseline, interleaved JPEG batches larger than 50. The probe copies every
output to host memory and verifies all 64 RGB hashes match. It also encodes
one of those CUDA-resident RGB images through `NVJPEG_ENC_BACKEND_GPU` at
quality 90, then independently decodes the resulting JPEG with FFmpeg. The
test compares both decoded RGB buffers to their respective source. Temporary
JPEG/RGB data and the Nsight report are deleted after the check; only numeric
evidence is retained in the [decode and encode result](nvjpeg-gpu-codec-kernel38.json).

On native `7.2.8-38-rtx-spark-npu`, NVIDIA `615.78.08`, CUDA `13.4.2-1`,
the batch passed. The 172,800-byte nvJPEG RGB output differed from software
by mean squared error **0.03965**, PSNR **62.15 dB**, and maximum channel
error **2**. Nsight Systems' CUDA-kernel trace observed the nvJPEG
`DecodeBatchedCujpeg::decodeDcHuffman`, batch parser, VLD and YCbCr→RGB
kernels. The GPU encoder produced a 10,627-byte baseline 4:2:0 JPEG. Its
independently decoded RGB output has **38.41 dB PSNR** versus the source
RGB, and Nsight observed nvJPEG `encoding::ACKernel`, DCT and color-conversion
kernels. This establishes direct GPU-compute JPEG decode and encode with
bounded pixel checks.

The separate [capability query](nvjpeg-capability.json) reports zero dedicated
JPEG decoder and encoder engines and an architecture mismatch for the
hardware-only backend. These GPU-compute results do not change that result;
larger images, latency/power advantage, application adoption and post-resume
operation remain unqualified. The [earlier decode-only result](nvjpeg-gpu-batch-kernel38.json)
is preserved as a separate historical measurement.
