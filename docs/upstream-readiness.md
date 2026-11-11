# Upstream requirements

The source is suitable for review and further integration. It is not a claim
that every driver is ready for kernel submission or production deployment.

## Kernel interfaces

DSP, SCP and Pluton have Kconfig/Kbuild entries and hardware-independent KUnit
protocol tests. ACPI IDs select the devices; resource dimensions, firmware ABI
and message bounds are validated before access. There are no host product-name,
BIOS-version or module-srcversion allowlists in their runtime matching.

The DSP depends on the NPU/SROOT provider and AFE owner APIs. Those dependencies
need subsystem agreement, an upstreamable interface and ordering with their
implementations. The debugfs diagnostic interfaces also need maintainer review.
SCP's firmware dispatch check currently limits the supported mailbox ABI.
Pluton supplies metadata queries, not complete security-processor services.

## DSP lifetime and audio

Published operating buffers cannot yet be reclaimed. The driver retains memory
and module/runtime-PM references rather than assuming a task ACK stops DMA.
Verified whole-core shutdown, failure handling and suspend/remove behavior are
required before enabling DSP startup by default.

HiFi1 route-2 DL0/DL1 playback, primary HiFi5 route-3 UL1 capture, independent
duplex owners, repeated stream lifecycle and ASoC/SRAM retention have offline
fault and concurrency coverage. Native capture transport is implemented;
capture/duplex hardware qualification remains open. DSP 0.1.22 has short
playback transfer/restart evidence, but its device-only PM test failed to
restart firmware after D0. The later REINIT correction and post-wake audio/NPU
still need matching-artifact hardware tests. Complete analog endpoint coverage
and runtime autosuspend also remain open. See the
[interface matrix and evidence](platform-driver-status.md#current-dsp-interface-requirements).
The provider's release of successfully consumed upload staging is a separate
contract and does not establish DSP shutdown or release operating buffers.

## SPI HID and ALS

The SPI HID fixes depend on the prerequisite series recorded in
[upstream/spi-hid](../upstream/spi-hid/README.md), including its SPI-core coherent
RX dependency. They must be rebased onto the maintainer's selected baseline.
Existing author notices and sign-offs remain intact. Generated integration
patches require author-reviewed DCO sign-off before submission.

The HID ALS package carries the attributed upstream per-channel scale fix.
Prefer that upstream implementation in a kernel containing it rather than a
permanent standalone replacement.

## Submission checks

- Build affected module and built-in configurations on the target tree.
- Run KUnit plus the actual-function fault, user-copy and concurrency tests.
- Check ACPI/resource error paths, firmware truncations and unsupported ABIs.
- Validate hardware after a fresh boot with the exact submitted sources.
- Keep legal attribution, provenance and human-reviewed DCO sign-offs.

Offline builds and tests provide evidence for parser, ownership and error-path
behavior. They do not establish hardware portability, streaming correctness or
DMA shutdown. Current functionality and gaps are listed in
[platform-driver-status.md](platform-driver-status.md).
