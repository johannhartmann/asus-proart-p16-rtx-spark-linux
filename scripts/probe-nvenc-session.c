/* Minimal CUDA/NVENC session probe, independent of FFmpeg.
 * Build against a pinned nv-codec-headers checkout and installed CUDA driver:
 * cc -std=c11 -Wall -Wextra -I/opt/cuda/include \
 *   -I/path/to/nv-codec-headers/include \
 *   probe-nvenc-session.c -lcuda -lnvidia-encode -o probe-nvenc-session
 */
#include <stdio.h>
#include <stdint.h>
#include <cuda.h>
#include <ffnvcodec/nvEncodeAPI.h>

int main(void)
{
    CUdevice device;
    CUcontext context = NULL;
    void *encoder = NULL;
    uint32_t max_version = 0;
    NV_ENCODE_API_FUNCTION_LIST functions = { 0 };
    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS params = { 0 };
    NVENCSTATUS status;
    CUresult cuda_status;

    printf("header_api_version=0x%x\n", NVENCAPI_VERSION);
    status = NvEncodeAPIGetMaxSupportedVersion(&max_version);
    printf("driver_api_query_status=%d driver_max_api_version=0x%x\n",
           status, max_version);
    if (status != NV_ENC_SUCCESS ||
        ((NVENCAPI_MAJOR_VERSION << 4) | NVENCAPI_MINOR_VERSION) > max_version)
        return 2;

    cuda_status = cuInit(0);
    if (cuda_status != CUDA_SUCCESS) {
        printf("cuInit_status=%d\n", cuda_status);
        return 3;
    }
    cuda_status = cuDeviceGet(&device, 0);
    if (cuda_status != CUDA_SUCCESS) {
        printf("cuDeviceGet_status=%d\n", cuda_status);
        return 3;
    }
    cuda_status = cuCtxCreate(&context, NULL, 0, device);
    if (cuda_status != CUDA_SUCCESS) {
        printf("cuCtxCreate_status=%d\n", cuda_status);
        return 3;
    }

    functions.version = NV_ENCODE_API_FUNCTION_LIST_VER;
    status = NvEncodeAPICreateInstance(&functions);
    printf("create_instance_status=%d\n", status);
    if (status != NV_ENC_SUCCESS) {
        cuCtxDestroy(context);
        return 4;
    }

    params.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
    params.deviceType = NV_ENC_DEVICE_TYPE_CUDA;
    params.device = context;
    params.apiVersion = NVENCAPI_VERSION;
    status = functions.nvEncOpenEncodeSessionEx(&params, &encoder);
    printf("open_session_status=%d\n", status);
    if (encoder != NULL)
        functions.nvEncDestroyEncoder(encoder);
    cuCtxDestroy(context);
    return status == NV_ENC_SUCCESS ? 0 : 5;
}
