/* Minimal EGL/OpenGL NVENC session probe, independent of FFmpeg.
 * cc -std=c11 -Wall -Wextra -I/path/to/nv-codec-headers/include \
 *   probe-nvenc-session-opengl.c -lEGL -lGL -lnvidia-encode -o probe
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/gl.h>
#include <ffnvcodec/nvEncodeAPI.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    EGLConfig config;
    EGLint count = 0;
    void *encoder = NULL;
    uint32_t max_version = 0;
    NV_ENCODE_API_FUNCTION_LIST functions = {0};
    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS params = {0};
    NVENCSTATUS status;
    int result = 1;

    const EGLint config_attributes[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
        EGL_NONE
    };
    const EGLint pbuffer_attributes[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};

    PFNEGLQUERYDEVICESEXTPROC query_devices =
        (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform_display =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    if (query_devices && platform_display) {
        EGLDeviceEXT devices[16];
        EGLint device_count = 0;
        if (query_devices(16, devices, &device_count)) {
            for (EGLint i = 0; i < device_count; i++) {
                EGLDisplay candidate = platform_display(EGL_PLATFORM_DEVICE_EXT, devices[i], NULL);
                if (candidate == EGL_NO_DISPLAY || !eglInitialize(candidate, NULL, NULL))
                    continue;
                const char *egl_vendor = eglQueryString(candidate, EGL_VENDOR);
                if (egl_vendor && strstr(egl_vendor, "NVIDIA")) {
                    display = candidate;
                    break;
                }
                eglTerminate(candidate);
            }
        }
    }
    if (display == EGL_NO_DISPLAY || !eglBindAPI(EGL_OPENGL_API) ||
        !eglChooseConfig(display, config_attributes, &config, 1, &count) ||
        count != 1) {
        fprintf(stderr, "EGL initialization failed: 0x%x\n", eglGetError());
        goto done;
    }
    context = eglCreateContext(display, config, EGL_NO_CONTEXT, NULL);
    surface = eglCreatePbufferSurface(display, config, pbuffer_attributes);
    if (context == EGL_NO_CONTEXT || surface == EGL_NO_SURFACE ||
        !eglMakeCurrent(display, surface, surface, context)) {
        fprintf(stderr, "EGL context failed: 0x%x\n", eglGetError());
        goto done;
    }
    const char *vendor = (const char *)glGetString(GL_VENDOR);
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    printf("gl_vendor=%s gl_renderer=%s\n", vendor ? vendor : "unknown",
           renderer ? renderer : "unknown");
    if (!vendor || !renderer || strcmp(vendor, "NVIDIA Corporation") != 0 ||
        !strstr(renderer, "RTX Spark N1X")) {
        fprintf(stderr, "OpenGL context is not the N1X NVIDIA device\n");
        goto done;
    }

    printf("header_api_version=0x%x\n", NVENCAPI_VERSION);
    status = NvEncodeAPIGetMaxSupportedVersion(&max_version);
    printf("driver_api_query_status=%d driver_max_api_version=0x%x\n",
           status, max_version);
    if (status != NV_ENC_SUCCESS ||
        ((NVENCAPI_MAJOR_VERSION << 4) | NVENCAPI_MINOR_VERSION) > max_version)
        goto done;

    functions.version = NV_ENCODE_API_FUNCTION_LIST_VER;
    status = NvEncodeAPICreateInstance(&functions);
    printf("create_instance_status=%d\n", status);
    if (status != NV_ENC_SUCCESS)
        goto done;

    params.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
    params.deviceType = NV_ENC_DEVICE_TYPE_OPENGL;
    params.device = NULL;
    params.apiVersion = NVENCAPI_VERSION;
    status = functions.nvEncOpenEncodeSessionEx(&params, &encoder);
    printf("open_session_status=%d\n", status);
    if (encoder != NULL)
        functions.nvEncDestroyEncoder(encoder);
    result = status == NV_ENC_SUCCESS ? 0 : 5;

done:
    if (display != EGL_NO_DISPLAY) {
        eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        if (surface != EGL_NO_SURFACE)
            eglDestroySurface(display, surface);
        if (context != EGL_NO_CONTEXT)
            eglDestroyContext(display, context);
        eglTerminate(display);
    }
    return result;
}
