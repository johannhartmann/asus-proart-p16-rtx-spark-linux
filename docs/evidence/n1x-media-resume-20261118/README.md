# Media resume qualification preflight, 18 November 2026

The [before result](before-result.json) contains 35 passing media cases and
the known NVENC session failure on the P16. **No physical suspend occurred**;
there is no after-resume result. [`status.json`](status.json) records s2idle
selection, the active NVIDIA kernel suspend notifier mode and RTC identities.

The first test armed `/dev/rtc1` (ACPI TAD) with `rtcwake -m no -s 30` inside a
root helper that would have requested systemd suspend only after successful
alarm setup. Alarm setup returned `Input/output error`, so the helper stopped
before requesting suspend; see [`sleep-attempt.json`](sleep-attempt.json).
The independent `/dev/rtc0` (EFI RTC) alarm attempt returned `Invalid argument`;
see [`rtc0-alarm-attempt.log`](rtc0-alarm-attempt.log).

`UseKernelSuspendNotifiers: 1` is active. The repository's
[`validate-dsp-audio.py`](../../../scripts/validate-dsp-audio.py) rejects a
standalone PM request in this mode because it needs the verified VT handoff
before freezing the user slice. A manual or automatic media PM test must
preserve that ordering. A reliable wake source or an attended manual wake is
also needed before a physical test. Neither device-only nor physical media
resume is claimed here.
