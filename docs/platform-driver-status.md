# Platform driver status

This table describes the source tree. Installed module versions and hardware
results must be checked independently after a fresh boot.

| Component | Implemented | Remaining work |
| --- | --- | --- |
| NPU/SROOT | Serialized secure upload, signed-container bounds checking, numerical task validation and boot service | Fresh-boot qualification of changed sources; upstream accelerator integration |
| DSP | Secure load, boot notifications, bounded IPC and exclusive route-2 playback client | Complete-stream and retained-sleep hardware qualification, HiFi5 DSP capture, runtime autosuspend, verified shutdown and DMA reclamation |
| AFE | Firmware-described SRAM owner, PCM/IPC leases, checked ring/IRQ programming and DL0 DSP frontend | Hardware qualification with matching DSP/provider; published-buffer release |
| SCP | Read-only firmware log snapshots and bounded version/descriptor queries | Subsystem/API review and support for additional firmware ABIs |
| Pluton | ACPI PFI transport and typed PCBI metadata queries | Other services, including firmware control and key operations |
| SPI HID / ALS | ACPI IRQ/reset fixes, serialized report transactions, stream-only sensor matching and per-channel IIO scales | Maintainer dependency selection, target-tree testing and optical calibration |
| SPBM/hwmon | MT8901 telemetry ABI matching and platform-bus binding | Qualification on other supported systems and upstream review |

The modules use ACPI IDs/resources and checked firmware interfaces. Board ACPI
transformation and speaker firmware packages remain specific to the P16. Fixed
SoC register offsets and protocol constants are hardware definitions, not
host-system matching rules.

DSP publication retains operating DRAM, AFE SRAM and module/runtime-PM
references. A task ACK, STOP or IRQ disable does not prove whole-core DMA
quiescence. Device-bound ABI v3 clients reserve the selected provider before
DSP publication and add PM dependency ordering. Their v2-compatible upload
may release a consumed temporary image buffer
after a canonical successful upload; that does not release the DSP lifetime
lease. Failed or uncertain uploads retain staging and poison further requests.

Pluton exposes typed commands 4, 5 and 7 through `N1X_PLUTON_QUERY`. It builds
requests in the kernel and validates complete replies. There is no raw
userspace exchange. Unknown ioctls fail before submission. The CLI does not
retry failed requests.

Sensor measurements use the existing SPI HID sensor hub and HID ALS IIO
client. SCP mailbox diagnostics do not register a duplicate sensor. Descriptor
scales establish units, not optical calibration.

Run offline tests with `python3 -m unittest discover -s tests -v` and native
protocol tests as described in [platform/README.md](../platform/README.md).
Hardware qualification requires the exact built sources, a fresh boot and
bounded workload results. The installed-platform auditor writes a report and
performs diagnostic queries; it does not replace modules or start services.
