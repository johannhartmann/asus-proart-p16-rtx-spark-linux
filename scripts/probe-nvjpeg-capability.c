#include <stdio.h>
#include <nvjpeg.h>

static void probe_decoder(const char *name, nvjpegBackend_t backend) {
    nvjpegHandle_t handle = NULL;
    nvjpegStatus_t status = nvjpegCreateEx(backend, NULL, NULL, 0, &handle);
    printf("%s_create=%d\n", name, status);
    if (status != NVJPEG_STATUS_SUCCESS)
        return;
    unsigned int engines = 0, cores = 0, encoders = 0;
    printf("%s_decoder_info=%d\n", name,
           nvjpegGetHardwareDecoderInfo(handle, &engines, &cores));
    printf("%s_decoder_engines=%u cores_per_engine=%u\n", name, engines, cores);
    printf("%s_encoder_info=%d\n", name,
           nvjpegGetHardwareEncoderInfo(handle, &encoders));
    printf("%s_encoder_engines=%u\n", name, encoders);
    nvjpegEncoderState_t state = NULL;
    status = nvjpegEncoderStateCreateWithBackend(handle, &state,
                                                  NVJPEG_ENC_BACKEND_HARDWARE, 0);
    printf("%s_hardware_encoder_create=%d\n", name, status);
    if (status == NVJPEG_STATUS_SUCCESS)
        nvjpegEncoderStateDestroy(state);
    nvjpegDestroy(handle);
}

int main(void) {
    probe_decoder("default", NVJPEG_BACKEND_DEFAULT);
    probe_decoder("gpu_hybrid", NVJPEG_BACKEND_GPU_HYBRID);
    probe_decoder("hardware", NVJPEG_BACKEND_HARDWARE);
    return 0;
}
