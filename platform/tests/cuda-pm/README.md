# Retained CUDA/UVM context for native PM tests

This development-only C client keeps a primary CUDA context and one 4 KiB
managed allocation alive. It performs actual CUDA initialization, GPU memset,
synchronization and driver copies. It does not request sleep, change a power
profile, load a module or access physical registers. It is never installed by
any driver package or used at boot.

Build with the installed CUDA headers and NVIDIA driver library:

```sh
cc -O2 -Wall -Wextra -Werror -I/opt/cuda/include retain.c -lcuda -o retain
printf 'v\nq\n' | ./retain 17
```

Adapt the include directory for your CUDA installation. The smoke test must
print `CUDA_RETAIN_READY` and `CUDA_RETAIN_CHECK_PASS`, then exit successfully.
For a manual lifetime test, run `./retain 17` and `./retain 93` in two terminals.
Each process announces readiness after initializing its allocation. Type `v`
and Enter to verify every byte, and `q` and Enter to free its allocation and
release its context. EOF, invalid commands, a ten-minute input timeout, CUDA
errors or data mismatches fail the client. Newlines are ignored.

Perform separately authorized PM tests after both clients are ready. Verify
both allocations after every resume, then quit both clients and check their
exit statuses. Successful memory checks alone do not establish clean kernel
locking; also verify fresh UVM suspend/resume callback coverage, kernel logs,
Lockdep, DSP readiness and the normal audio/NPU workloads. Use the matching
kernel/module set and preserve a working recovery entry.

The [17 November native record](../../../docs/evidence/kernel36-native-20261117.json)
records two device-only PM cycles with two retained contexts, independently
checked buffer patterns and four successful UVM callbacks. The broader native
sequence separately covers physical s2idle, audio reloads and audio/NPU
operation after resume. The retained-context extension does not claim physical
sleep coverage with those allocations alive.
