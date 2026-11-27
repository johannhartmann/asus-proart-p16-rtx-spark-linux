// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <sys/ioctl.h>

#include "nvos.h"
#include "nv-ioctl.h"
#include "nv_escape.h"
#include "class/cl2080.h"

#define ENCODER_SUBDEVICE_QUERY 0x20808165
#define ENCODER_SESSION_CONTROL 0x20808163

struct subdevice {
    NvHandle client;
    NvHandle handle;
    bool queried;
    int query_fd;
};

static _Thread_local struct subdevice gpu;
static pthread_once_t resolver = PTHREAD_ONCE_INIT;
static int (*system_ioctl)(int, unsigned long, ...);

static void resolve_ioctl(void)
{
    system_ioctl = dlsym(RTLD_NEXT, "ioctl");
}

static void record_allocation(NvV32 status, NvV32 class_id,
                              NvHandle client, NvHandle handle)
{
    if (status == 0 && class_id == NV20_SUBDEVICE_0 && handle != 0)
        gpu = (struct subdevice){ .client = client, .handle = handle };
}

/*
 * Use the AArch64 ABI to forward x2 even for ioctls declared with no
 * argument. Pulling a possibly absent argument from a C va_list is undefined.
 */
__attribute__((visibility("default")))
int forward_ioctl(int fd, unsigned long request, uintptr_t argument) __asm__("ioctl");

int forward_ioctl(int fd, unsigned long request, uintptr_t argument)
{
    pthread_once(&resolver, resolve_ioctl);
    if (system_ioctl == NULL) {
        errno = ENOSYS;
        return -1;
    }

    void *const arg = (void *)argument;
    if (_IOC_TYPE(request) != NV_IOCTL_MAGIC || arg == NULL)
        return system_ioctl(fd, request, arg);

    unsigned number = _IOC_NR(request);
    unsigned size = _IOC_SIZE(request);
    void *data = arg;
    if (number == NV_ESC_IOCTL_XFER_CMD && size == sizeof(nv_ioctl_xfer_t)) {
        const nv_ioctl_xfer_t *transfer = arg;
        number = transfer->cmd;
        size = transfer->size;
        data = (void *)transfer->ptr;
    }

    NVOS54_PARAMETERS *control = NULL;
    if (number == NV_ESC_RM_CONTROL && size == sizeof(NVOS54_PARAMETERS))
        control = data;

    // The candidate GPU object came from this thread and client. Require the
    // immediately preceding query to confirm that it is still usable.
    const bool fix = gpu.queried && fd == gpu.query_fd && control != NULL
        && control->cmd == ENCODER_SESSION_CONTROL && control->paramsSize == 4
        && control->hClient == gpu.client && control->hObject == 0;
    gpu.queried = false;
    if (fix)
        control->hObject = gpu.handle;

    const int result = system_ioctl(fd, request, arg);
    const int saved_errno = errno;
    if (fix)
        control->hObject = 0;

    if (result == 0 && data != NULL && number == NV_ESC_RM_ALLOC) {
        if (size == sizeof(NVOS21_PARAMETERS)) {
            const NVOS21_PARAMETERS *allocation = data;
            record_allocation(allocation->status, allocation->hClass,
                              allocation->hRoot, allocation->hObjectNew);
        } else if (size == sizeof(NVOS64_PARAMETERS)) {
            const NVOS64_PARAMETERS *allocation = data;
            record_allocation(allocation->status, allocation->hClass,
                              allocation->hRoot, allocation->hObjectNew);
        }
    }

    if (result == 0 && control != NULL && control->cmd == ENCODER_SUBDEVICE_QUERY
            && control->paramsSize == 1 && control->status == 0
            && gpu.handle != 0 && control->hClient == gpu.client
            && control->hObject == gpu.handle) {
        gpu.queried = true;
        gpu.query_fd = fd;
    }
    errno = saved_errno;
    return result;
}
