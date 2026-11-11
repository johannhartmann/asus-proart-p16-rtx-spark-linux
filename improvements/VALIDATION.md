# Hardware validation and remaining work

The initial observations below are from an ASUS ProArt P16 H7607BA, N1X ARM64,
BIOS 303. A separate BIOS 305 record follows.
They describe what was tested, not certification of every distro or BIOS.

| Area | Evidence | Limits |
|---|---|---|
| Kernel and GPU | Full native ARM64 Linux 7.3 build and successful boot; NVIDIA 615.78.08 active | The compact vanilla7.3 patch export is source-tested; its exact standalone combination has not had a second full kernel build |
| Coordinated s2idle | Admission for all 20 CPUs; three manual lid cycles of roughly 380, 152 and 1221 seconds recovered GPU/Wi-Fi/SD | No direct physical DRIPS residency measurement; one earlier external-module trial had intermittent Wi-Fi scanning failure |
| Sleep energy | 92.296 Wh to 91.847 Wh across 1225.775 s: 0.449 Wh, about 1.319 W including transitions | One long integrated-kernel trial, gauge timing limits precision; not a new measurement of the final sensor-reset revision |
| ASUS WMI | Loaded on ARM64; firmware profiles, battery threshold and fan RPM exposed | Factory fan policy retained; no custom fan-curve thermal qualification |
| ASUS optional initialization | Architecture, i8042 and per-fan capability harnesses pass; no corresponding warnings on the tested boot | Other ASUS machines not physically tested |
| SPI-HID/light sensor | `_RST` succeeds; GPIO 190 interrupt and HID/IIO hub appear; cover/light test changes 0 to about 2175 lux then ambient | Absolute calibration unverified |
| Sensor resume | One lid s2idle cycle of about 57s; sensor reports 13 lux after resume; SPI error/timeout counters 0; GPU/audio active | Repeated cycles and long sleep-power measurement with this revision pending |
| Audio | DAPM route correction and local PipeWire graph work after boot; jack switching exercised | OEM-derived tuning is not redistributed; see audio guide for the public configuration's validation scope |
| Telemetry | Production firmware parsing, probe-policy and RAM-backed MMIO tests; exported patch compiles against the running Linux 7.3 headers; driver loaded on this hardware | Channel availability depends on firmware; absolute energy calibration and inherited diagnostic interpretation remain limited |
| Keys | Fn+Esc and ASUS application key received/usable | Fn+F7 external display selection awaits an external monitor |
| Bluetooth / USB | A later manual s2idle cycle kept a connected USB 3 device readable and restored AirPods audio without manual reconnection | One test cycle; USB4/external display paths and broad peripheral coverage remain unvalidated |

BIOS eligibility is intentionally not a version whitelist. The code still
checks model/platform and relevant firmware contracts. This does not mean
all BIOS releases have been physically tested.

No DSDT override was used for these BIOS 303 tests. The upstream BIOS 300 ACPI
builder remains historical reference; it is not required by this patch guide.

The exported source tests exercise actual patched functions using stubs,
including ASan/UBSan where specified. They cannot prove firmware cooperation,
hardware power draw, wake reliability or audio tuning quality.

## Export verification (2026-11-04)

- All 83 kernel patches apply to pristine Linux 7.3 with `--fuzz=0`.
- Reference config plus fragment survives `make olddefconfig`; all exported
  kernel source harnesses pass on that resulting tree.
- Telemetry patch applies to its pinned source; firmware parser, probe policy
  and MMIO callback tests pass, and `spbm.ko` builds against the running ARM64
  Linux 7.3 headers. No module is loaded by these build checks.
- Audio route patch applies cleanly to that tree; the public graph and
  hardware-gate export checks pass. The neutral graph has not had an isolated
  runtime/audio validation or physical listening test.

## MT7925 follow-up validation (2026-11-07)

The unmodified upstream MLO correction was fully compiled and booted in an
isolated ARM64 kernel using the same Linux 7.3 base and P16 patch set. Both
5975 MHz and 5500 MHz links were active. Over 120 seconds, simultaneous ping
tests received 240/240 replies each from the gateway, a LAN host and Internet
through VPN: mean latencies 10.6/10.9/15.0 ms, with isolated peaks near 274 ms.
A separate 180-second operator walk received 360/360 gateway, 359/360 LAN and
360/360 Internet replies, means 5.3/6.5/9.8 ms and maximum near 107 ms.
No reconnects occurred during those intervals. The walk retained the same AP,
so inter-AP roaming was not validated. Initial supplicant scan/link/group-key
warnings remain; suspend/resume with this Wi-Fi change is still untested.
These observations do not establish that all MT7925 problems are fixed.

The compact export remains a separate source-tested patch combination, not a
claim of a full standalone build or physical qualification of every feature.
Only the H7607BA BIOS 303/305 20-CPU configurations have been physically tested here;
18-CPU N1X admission is tentative and depends on the same structural firmware
checks; no 18-CPU physical boot, suspend, resume or power result is available.

## Independent sleep report (2026-11-08)

A [second H7607BA BIOS 303 owner reported](https://github.com/omacom/omarchy-pkgs/pull/1958#issuecomment-6715195039)
that the identical 1120-1125 sleep patches changed immediate wake after about
4-6 seconds into sustained s2idle. Their two usable energy intervals measured
approximately 1.546 W over 3 h 17 min and 1.559 W over 33 min. This is an
independent report on another 20-CPU unit, not an additional measurement on
the laptop used for this export. Their other test series served as controls;
read the linked report for the complete setup and attribution.

That owner also reported RTC alarms not waking the patched machine and one
early wake involving a USB mouse receiver. Stock behavior cannot be compared
for timed wake because it woke immediately. Timed RTC wake is not validated
by this export; USB receivers and other wake sources may affect sleep. These
observations do not establish a firmware root cause or a new fix.

## BIOS 305 validation (2026-11-10)

On the same 20-CPU H7607BA with BIOS H7607BA.305, experimental kernel
`7.3.0-44.10` admitted all 20 CPUs, three parent levels and seven compositions,
without the previous `-22` rejection. One manual lid cycle lasted 6 min
34.688 s. Battery discharge was 0.209 Wh over a 400.983 s measurement interval,
about 1.876 W including transitions and 6.295 s awake. The suspend success
counter increased by one and the failure counter remained zero; NVIDIA,
Wi-Fi and the ambient light sensor recovered.

The main `7.3.0-44.10` kernel subsequently booted with coordinated admission
and no failed services. A suspend-power test on that main boot was not run.
These are tests of the integrated distro kernels, not a separate full build
or hardware qualification of this compact standalone export. The BIOS 303
results above remain valid for their original kernels and test conditions.

Patch 1126 retains the validated candidate bytes while using the next free
series number. It accepts the known enabled parent descriptors and exact
paired system timing sentinel without changing firmware timing values.
The policy harness extracts the actual admission functions; the governor
harness extracts `cpu_system_power_down_ok` and checks unconstrained QoS,
finite QoS rejection and disabled states against that sentinel.

One cycle and battery-gauge energy do not prove physical DRIPS residency or
a steady-state power rate. No 18-CPU hardware was tested. RTC timed wake
remains unvalidated; this change does not claim an RTC wake fix.

## Fallback latency overflow follow-up

Patch 1127 saturates the historical fallback latency addition before converting
to nanoseconds. An enabled BIOS 305 paired `U32_MAX` sentinel therefore remains
`U32_MAX` instead of wrapping to 6609 microseconds. The real setup/selection
harness reproduces the overflow before the fix and checks sentinel, boundary,
finite, coordinated and non-N1x cases after it. Patch 1125 remains unchanged.
This source regression test adds no physical sleep or DRIPS residency evidence.

## Governor harness correction

The governor regression now extracts the actual `pm_qos.h` constants and their
`S32_MAX` definition from the prepared kernel. The no-constraint value is
`S32_MAX` microseconds (2147483647000 ns), not -1 or an infinite nanosecond
budget. A finite constraint of `INT32_MAX - 1` rejects the BIOS 305 timing
sentinel. Removing the governor's explicit no-constraint exception makes the
regression fail. This corrects the test mocks; no kernel behavior is changed.
