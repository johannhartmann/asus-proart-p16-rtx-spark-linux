/* Exercise GPU-assisted nvJPEG batch decode and GPU JPEG encoding. */
#include <cuda_runtime_api.h>
#include <nvjpeg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BATCH 64

static void die(const char *step, int status) {
    fprintf(stderr, "%s failed: %d\n", step, status);
    exit(1);
}

#define NV(step, call) do { \
    nvjpegStatus_t status_ = (call); \
    if (status_ != NVJPEG_STATUS_SUCCESS) die(step, status_); \
} while (0)
#define CU(step, call) do { \
    cudaError_t status_ = (call); \
    if (status_ != cudaSuccess) die(step, status_); \
} while (0)

static uint64_t hash_bytes(const unsigned char *data, size_t size) {
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < size; ++i) {
        hash ^= data[i];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "Usage: %s INPUT.jpg OUTPUT.rgb ENCODED.jpg\n", argv[0]);
        return 2;
    }
    FILE *input = fopen(argv[1], "rb");
    if (!input) { perror(argv[1]); return 1; }
    if (fseek(input, 0, SEEK_END)) { perror("fseek"); return 1; }
    long file_size = ftell(input);
    if (file_size <= 0 || file_size > 16 * 1024 * 1024) {
        fprintf(stderr, "JPEG size outside 1..16 MiB\n");
        return 1;
    }
    rewind(input);
    unsigned char *jpeg = malloc((size_t)file_size);
    if (!jpeg || fread(jpeg, 1, (size_t)file_size, input) != (size_t)file_size)
        die("read JPEG", 1);
    fclose(input);

    nvjpegHandle_t handle = NULL;
    nvjpegJpegState_t state = NULL;
    cudaStream_t stream = NULL;
    NV("nvjpegCreateEx GPU_HYBRID",
       nvjpegCreateEx(NVJPEG_BACKEND_GPU_HYBRID, NULL, NULL, 0, &handle));
    NV("nvjpegJpegStateCreate", nvjpegJpegStateCreate(handle, &state));
    CU("cudaStreamCreate", cudaStreamCreate(&stream));
    int components = 0, widths[NVJPEG_MAX_COMPONENT] = {0};
    int heights[NVJPEG_MAX_COMPONENT] = {0};
    nvjpegChromaSubsampling_t subsampling;
    NV("nvjpegGetImageInfo", nvjpegGetImageInfo(handle, jpeg, (size_t)file_size,
                                               &components, &subsampling,
                                               widths, heights));
    if (components != 3 || widths[0] <= 0 || heights[0] <= 0 ||
        widths[0] > 4096 || heights[0] > 4096)
        die("unsupported JPEG dimensions/components", components);
    const int width = widths[0], height = heights[0];
    const size_t bytes = (size_t)width * height * 3;
    nvjpegImage_t destinations[BATCH] = {0};
    const unsigned char *sources[BATCH];
    size_t lengths[BATCH];
    for (int i = 0; i < BATCH; ++i) {
        sources[i] = jpeg;
        lengths[i] = (size_t)file_size;
        destinations[i].pitch[0] = (size_t)width * 3;
        CU("cudaMalloc output", cudaMalloc((void **)&destinations[i].channel[0], bytes));
    }
    NV("nvjpegDecodeBatchedInitialize",
       nvjpegDecodeBatchedInitialize(handle, state, BATCH, 4,
                                     NVJPEG_OUTPUT_RGBI));
    NV("nvjpegDecodeBatched",
       nvjpegDecodeBatched(handle, state, sources, lengths, destinations, stream));
    CU("cudaStreamSynchronize", cudaStreamSynchronize(stream));
    unsigned char *pixels = malloc(bytes);
    if (!pixels) die("malloc pixels", 1);
    uint64_t first_hash = 0;
    for (int i = 0; i < BATCH; ++i) {
        CU("cudaMemcpy output", cudaMemcpy(pixels, destinations[i].channel[0],
                                           bytes, cudaMemcpyDeviceToHost));
        uint64_t hash = hash_bytes(pixels, bytes);
        if (!i) {
            first_hash = hash;
            FILE *output = fopen(argv[2], "wb");
            if (!output || fwrite(pixels, 1, bytes, output) != bytes || fclose(output))
                die("write RGB output", 1);
        } else if (hash != first_hash) {
            fprintf(stderr, "Batch output %d differs from first image\n", i);
            return 1;
        }
    }
    nvjpegEncoderState_t encoder = NULL;
    nvjpegEncoderParams_t parameters = NULL;
    NV("nvjpegEncoderStateCreateWithBackend GPU",
       nvjpegEncoderStateCreateWithBackend(handle, &encoder,
                                           NVJPEG_ENC_BACKEND_GPU, stream));
    NV("nvjpegEncoderParamsCreate",
       nvjpegEncoderParamsCreate(handle, &parameters, stream));
    NV("nvjpegEncoderParamsSetQuality",
       nvjpegEncoderParamsSetQuality(parameters, 90, stream));
    NV("nvjpegEncoderParamsSetSamplingFactors",
       nvjpegEncoderParamsSetSamplingFactors(parameters, NVJPEG_CSS_420, stream));
    NV("nvjpegEncodeImage GPU",
       nvjpegEncodeImage(handle, encoder, parameters, &destinations[0],
                         NVJPEG_INPUT_RGBI, width, height, stream));
    CU("cudaStreamSynchronize encode", cudaStreamSynchronize(stream));
    size_t encoded_size = 0;
    NV("nvjpegEncodeRetrieveBitstream size",
       nvjpegEncodeRetrieveBitstream(handle, encoder, NULL, &encoded_size, stream));
    if (!encoded_size || encoded_size > 16 * 1024 * 1024)
        die("encoded JPEG size", (int)encoded_size);
    unsigned char *encoded = malloc(encoded_size);
    if (!encoded) die("malloc encoded JPEG", 1);
    NV("nvjpegEncodeRetrieveBitstream",
       nvjpegEncodeRetrieveBitstream(handle, encoder, encoded, &encoded_size,
                                     stream));
    FILE *encoded_output = fopen(argv[3], "wb");
    if (!encoded_output || fwrite(encoded, 1, encoded_size, encoded_output) != encoded_size ||
        fclose(encoded_output))
        die("write encoded JPEG", 1);
    printf("{\"backend\":\"NVJPEG_BACKEND_GPU_HYBRID\",\"batch\":%d,"
           "\"width\":%d,\"height\":%d,\"subsampling\":%d,"
           "\"rgb_bytes\":%zu,\"batch_output_identical\":true,"
           "\"rgb_fnv1a64\":\"%016llx\",\"encode_backend\":\"NVJPEG_ENC_BACKEND_GPU\","
           "\"encoded_jpeg_bytes\":%zu}\n",
           BATCH, width, height, subsampling, bytes,
           (unsigned long long)first_hash, encoded_size);
    free(encoded);
    NV("nvjpegEncoderParamsDestroy", nvjpegEncoderParamsDestroy(parameters));
    NV("nvjpegEncoderStateDestroy", nvjpegEncoderStateDestroy(encoder));
    for (int i = 0; i < BATCH; ++i)
        CU("cudaFree output", cudaFree(destinations[i].channel[0]));
    free(pixels);
    free(jpeg);
    CU("cudaStreamDestroy", cudaStreamDestroy(stream));
    NV("nvjpegJpegStateDestroy", nvjpegJpegStateDestroy(state));
    NV("nvjpegDestroy", nvjpegDestroy(handle));
    return 0;
}
