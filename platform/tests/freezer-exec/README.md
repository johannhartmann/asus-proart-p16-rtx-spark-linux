# Isolated exec/freezer regression

These two static userspace programs are for a disposable ARM64 QEMU guest with
`CONFIG_PM_DEBUG=y`, `CONFIG_CGROUPS=y` and cgroup v2 support. They never belong
in an installed initramfs. The controller refuses execution unless it is PID 1
and the DMI vendor is QEMU. Do not execute it on the workstation.

```sh
cc -static -O2 -Wall -Wextra -Werror init.c -o /path/to/private-build/init
cc -static -O2 -Wall -Wextra -Werror -pthread stress.c -o /path/to/private-build/stress
```

Put the binaries at `/init` and `/stress` in the guest's initramfs, with `/dev`,
`/sys`, `/proc` directories and `/dev/console` (character 5:1). Boot the exact
candidate Image in QEMU/KVM with a serial console, no networking, no device
passthrough and a read-only virtual boot disk. Bound the VM to 90 seconds; kill
only the owned VM on failure. No root or host power-management writes are needed
for the VM launcher.

The controller starts sixteen owned helpers. Each creates two waiting threads
and a third thread that repeatedly executes `/stress`. It selects **guest-only**
`pm_test=freezer`, a 1.5-second freezer timeout and zero test delay. It compares
twelve direct freezer attempts with twelve attempts after freezing only its own
helper cgroup. It then thaws and kills its helpers, resets the guest test mode
and powers off. Inspect every return value; the raw failure count depends on
scheduling and is not required to be twelve on every platform.

On 14 November 2026, an EFI/KVM guest using the exact kernel32 Image produced
`raw_ok=0 raw_busy=12 prefrozen_ok=12`. Guest runtime was 52.4 seconds. The host
boot ID, loaded drivers and PM selection were unchanged. This demonstrates the
exec/freezer race and the cgroup sequencing effect. It does **not** test NVIDIA
notifiers, VT acknowledgements, physical DSP retention, real sleep or wakeup.
