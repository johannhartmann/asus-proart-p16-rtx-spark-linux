# nvJPEG GPU-compute decode on native kernel38

The [reproducible test](../../../scripts/check-nvjpeg-gpu-batch.py) generates a
320×180 baseline 4:2:0 JPEG from FFmpeg `testsrc2`, compiles the pinned
[`nvJPEG` probe](../../../scripts/probe-nvjpeg-gpu-batch.c), and decodes a
64-image batch through `NVJPEG_BACKEND_GPU_HYBRID` into CUDA device memory.
The installed CUDA headers document GPU-assisted Huffman decoding for
baseline, interleaved JPEG batches larger than 50. The probe copies every
output to host memory and verifies all 64 RGB hashes match. The test decodes
the same JPEG with FFmpeg software and compares pixels. Temporary JPEG/RGB
data and the Nsight report are deleted after the check; only numeric evidence
is retained in the [JSON result](nvjpeg-gpu-batch-kernel38.json).

On native `7.2.8-38-rtx-spark-npu`, NVIDIA `615.78.08`, CUDA `13.4.2-1`,
the batch passed. The 172,800-byte nvJPEG RGB output differed from software
by mean squared error **0.03965**, PSNR **62.15 dB**, and maximum channel
error **2**. Nsight Systems' CUDA-kernel trace observed the nvJPEG
`DecodeBatchedCujpeg::decodeDcHuffman`, batch parser, VLD and YCbCr→RGB
kernels. This is direct GPU-compute JPEG work and correct decoded pixels
within the bounded software comparison.

The separate [capability query](nvjpeg-capability.json) reports zero dedicated
JPEG decoder and encoder engines and an architecture mismatch for the
hardware-only backend. This GPU-hybrid result does not change that result;
JPEG encoding, larger images, latency/power advantage, application adoption
and post-resume operation remain unqualified.
