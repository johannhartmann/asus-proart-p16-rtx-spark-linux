# NVIDIA notifier suspend ordering

This optional systemd integration switches to VT63 **before** systemd freezes
`user.slice`, and restores the previous VT after suspend, an aborted suspend or
a preparation failure. It is for `UseKernelSuspendNotifiers: 1`; it sends no
commands to `/proc/driver/nvidia/suspend`, changes no module parameters and
does not load firmware or implement a driver startup path.

The VT handoff lets the compositor acknowledge the console release before
freezing. Early cgroup freezing avoids the multithreaded `exec()`/PM-freezer
race reproduced by [the isolated regression](../../tests/freezer-exec/README.md).
Enabling early freezing without the handoff can instead block the console
switch. The unit dependency makes a failed handoff abort the sleep request;
`ExecStopPost` restores the VT even when preparation fails. A manual intervening
VT change is respected. The power profile and audio defaults are untouched.

The shell helper is ordinary system integration using `kbd` and systemd, with
no ASUS identifiers or Python dependency. The kernel modules still own all
firmware, DMA and device PM operations. NVIDIA's packaged `nvidia-sleep.sh`
provides a similar VT handoff for its **procfs** PM path, but exits without that
handoff when the procfs interface is absent; it cannot substitute for this
notifier-path ordering.

Build and inspect the package:

```sh
makepkg --cleanbuild
bsdtar -tf nvidia-notifier-sleep-0.1.0-1-any.pkg.tar.*
```

Installing it adds a dependency/drop-in to `systemd-suspend.service`; no
`systemctl enable` is needed. It overrides the vendor's no-freeze environment
setting only for suspend. It does not enable hibernation. Remove the package
and run `systemctl daemon-reload` to restore the vendor policy.

**Qualification:** this is a candidate, not a claim of working physical sleep.
Six shell regression cases and three mocked systemd transactions passed. The
same VT-before-freezer sequence passed native device-only PM, but physical
sleep and the packaged normal suspend path still need qualification with a
fresh, continuously enabled Lockdep validator. Do not install this package
alone as a substitute for the matching kernel/driver corrections described in
[the suspend candidate](../../../docs/suspend-candidate.md).

Developer tests (no root, real console switch or physical sleep):

```sh
python test_vt.py
python test_systemd.py
```

The second test requires an active user systemd manager. It creates only its
own temporary runtime units, substitutes the console commands and removes the
units afterward. Python is used only for these development tests and is not
part of the installed package.
