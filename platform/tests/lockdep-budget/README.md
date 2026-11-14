# Lockdep dependency-budget regression

This explicit test module is for an isolated QEMU guest. It refuses other DMI
vendors and requires `run_test=1`; no package or service installs or loads it.
It does not access physical devices or change the workstation's Lockdep state.

```sh
make -C /path/to/candidate/kernel M="$PWD/platform/tests/lockdep-budget" W=1 modules
```

Load the matching artifact **inside the guest** with `run_test=1`. It creates
300 lock classes and takes every ordered pair, generating 44,850 valid dependency
edges with a maximum mutex nesting depth of two. The old 32,768-entry debug
configuration should report exhaustion and reject module initialization with
`ENOSPC`. A candidate with sufficient capacity must print
`LOCKDEP_BUDGET_PASS pairs=44850 debug_locks=1`, without a warning or deadlock.

This reproduces a static capacity limit. It does not replace real NVIDIA,
container, audio and suspend qualification on the physical machine.

On 14 November 2026, the negative control booted the exact kernel32 Image in
an EFI/KVM guest and reproduced `MAX_LOCKDEP_ENTRIES too low`; initialization
returned `ENOSPC` as expected. The host kernel and its Lockdep state were not
changed. The expanded-budget kernel33 positive control passed all 44,850 pairs
with `debug_locks=1`, with no kernel warnings. The exact raw Image SHA-256 was
`935b81297137561ded40567e2c860d45cb014f72de3eb958cc01963d468170e1`.
This is isolated VM evidence, not native graphics/workload qualification.
