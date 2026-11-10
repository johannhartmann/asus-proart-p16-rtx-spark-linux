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

The route-2 DL0 frontend has offline fault and concurrency coverage. Repeated stream lifecycle and ASoC/SRAM retention have offline coverage. Full-stream
hardware qualification, runtime autosuspend, DSP capture and additional endpoints remain open. The
provider's release of successfully consumed upload staging is a separate
contract and does not establish DSP shutdown.

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
