// SPDX-License-Identifier: MIT
/* Development-only CUDA/UVM lifetime client. Does not request system sleep. */
#include <cuda.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static int checked(CUresult result, const char *operation)
{
 const char *name = "unknown";
 if (result == CUDA_SUCCESS) return 1;
 cuGetErrorName(result, &name);
 fprintf(stderr, "%s: %s\n", operation, name);
 return 0;
}
#define CUDA(call) do { if (!checked((call), #call)) goto out; } while (0)
int main(int argc, char **argv)
{
 CUdevice device = 0;
 CUcontext context = NULL;
 CUdeviceptr memory = 0;
 unsigned char bytes[4096];
 char *end;
 long pattern;
 int result = 1;
 if (argc != 2) return 2;
 pattern = strtol(argv[1], &end, 10);
 if (!*argv[1] || *end || pattern < 1 || pattern > 255) return 2;
 setvbuf(stdout, NULL, _IONBF, 0);
 CUDA(cuInit(0));
 CUDA(cuDeviceGet(&device, 0));
 CUDA(cuDevicePrimaryCtxRetain(&context, device));
 CUDA(cuCtxSetCurrent(context));
 CUDA(cuMemAllocManaged(&memory, sizeof(bytes), CU_MEM_ATTACH_GLOBAL));
 CUDA(cuMemsetD8(memory, (unsigned char)pattern, sizeof(bytes)));
 CUDA(cuCtxSynchronize());
 printf("CUDA_RETAIN_READY pattern=%ld bytes=%zu\n", pattern, sizeof(bytes));
 for (;;) {
  struct pollfd input = { .fd = STDIN_FILENO, .events = POLLIN };
  char command;
  int ready = poll(&input, 1, 600000);
  if (ready < 0 && errno == EINTR) continue;
  if (ready <= 0 || read(STDIN_FILENO, &command, 1) != 1) goto out;
  if (command == '\n' || command == '\r') continue;
  if (command == 'q') { result = 0; break; }
  if (command != 'v') goto out;
  CUDA(cuMemcpyDtoH(bytes, memory, sizeof(bytes)));
  CUDA(cuCtxSynchronize());
  for (size_t i = 0; i < sizeof(bytes); i++) {
   if (bytes[i] != (unsigned char)pattern) {
    fprintf(stderr, "CUDA_RETAIN_MISMATCH offset=%zu\n", i);
    goto out;
   }
  }
  printf("CUDA_RETAIN_CHECK_PASS pattern=%ld bytes=%zu\n", pattern, sizeof(bytes));
 }
out:
 if (memory && !checked(cuMemFree(memory), "cuMemFree")) result = 1;
 if (context && !checked(cuDevicePrimaryCtxRelease(device), "cuDevicePrimaryCtxRelease")) result = 1;
 return result;
}
