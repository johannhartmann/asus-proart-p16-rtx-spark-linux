# Platform driver status

This table describes implemented source features, not hardware qualification.
Check installed module identities and the recorded results separately. Builds,
offline tests and firmware-ready notifications do not qualify audio or sleep.

| Component | Implemented | Remaining work |
| --- | --- | --- |
| NPU/SROOT | Serialized secure upload, signed-container bounds checking, numerical task validation and boot service | Fresh-boot qualification of changed sources; upstream accelerator integration |
| DSP | Secure load, bounded IPC, HiFi1 route-2 playback, primary HiFi5 route-3 capture, independent duplex owners and REINIT resume reconstruction | Capture/duplex and retained-sleep hardware qualification, runtime autosuspend, verified shutdown and DMA reclamation |
| AFE | Firmware-described SRAM owner, PCM/IPC leases, checked ring/IRQ programming, DL0/DL1 playback and UL1 capture frontends | Complete endpoint and PM qualification with matching DSP/provider; published-buffer release |
| SCP | Read-only firmware log snapshots and bounded version/descriptor queries | Subsystem/API review and support for additional firmware ABIs |
| Pluton | ACPI PFI transport and typed PCBI metadata queries | Other services, including firmware control and key operations |
| SPI HID / ALS | ACPI IRQ/reset fixes, serialized report transactions, stream-only sensor matching and per-channel IIO scales | Maintainer dependency selection, target-tree testing and optical calibration |
| SPBM/hwmon | MT8901 telemetry ABI matching and platform-bus binding | Qualification on other supported systems and upstream review |

The modules use ACPI IDs/resources and checked firmware interfaces. Board ACPI
transformation and speaker firmware packages remain specific to the P16. Fixed
SoC register offsets and protocol constants are hardware definitions, not
host-system matching rules.

## Current DSP interface requirements

These interfaces have independent versions. Matching one does not establish
compatibility with the others; use the matching provider, DSP and AFE bundle.

| Boundary | Required interface | Meaning |
| --- | --- | --- |
| DSP → NPU/SROOT provider | [`n1x_sroot_client_ops_v4()`](../platform/dsp/n1x_sroot_client.h) | Scoped provider handle, publication lease and retained-sleep votes; wraps the v3 base operations. |
| DSP resume → SROOT provider | [`n1x_sroot_reinit_dsp_v1`](../platform/dsp/n1x_sroot_client.h) | Separately versioned, typed REINIT export required at probe alongside the v4 table. |
| AFE → DSP PCM client | [`N1X_ADSP_PRIMARY_ABI = 3`](../platform/dsp/n1x_adsp_client.h) | Exact ABI check; retained stream lifecycle, DL0/DL1 selection, UL1 capture and independent playback/capture owners. |
| DSP → AFE SRAM owner | [`mt8901_afe_sram_endpoint.abi_version = 2`](../platform/dsp/mt8901-afe-sram.h) | Checked endpoint, ring and IRQ ownership. This is separate from PCM ABI 3. |

Legacy provider v1/v2 uploads and the v3 operations table remain compatibility
interfaces. The current DSP requires v4 **and** the additive REINIT export.
The v2 upload-result layout describes staging release, not the minimum provider
version. See [candidate preparation](driver-qualification.md#reproducible-candidates)
for the pinned provider source.

HiFi1 tasks 7/16 provide one playback stream on DL0 **or** DL1. Primary HiFi5
tasks 23/21 provide UL1 capture; one playback and one capture owner may coexist.
The secondary HiFi5 has boot/PM support but no PCM stream. Firmware startup,
`dsp_playback` and `dsp_capture` are opt-in. Native capture transport is
implemented; beamforming and noise suppression are not established capabilities.

## Recorded hardware evidence

The detailed, versioned record is in [the audio review](audio-review.md);
the required next tests are in [driver qualification](driver-qualification.md).

| Tested artifact | Observed result | Qualification boundary |
| --- | --- | --- |
| NPU baseline, kernel `7.2.8-23-rtx-spark-npu`, srcversion `AA4C27A61D0319E02A71961` | 16 correct cuDLA outputs, including five reuse submissions | That baseline only; not a later provider or DSP resume path. |
| DSP 0.1.22, AFE `417B4A1282694D05F8C7B04`, kernel `7.2.8-31-rtx-spark-npu` | S16_LE/S24_LE 48-kHz stereo transfer to SRAM, consumed-position notifications, restart/reopen/underrun recovery | Short playback transport/lifecycle tests; not all analog endpoints, capture or sleep. |
| DSP 0.1.22, device-only PM test, boot `76a1c35d` | D3 acknowledged; D0 lost startup state and all three DSPs entered protected errors | Failed resume test, zero completed sleep cycles; not successful standby. |
| DSP 0.1.23 REINIT correction and 0.1.24 capture/duplex source | Offline coverage and builds; three-core startup recorded separately in the audio review | REINIT resume, capture/duplex and post-wake audio/NPU need their own matching-artifact hardware qualification. |
| DSP 0.1.24, AFE `537B927FCEADD3EADCDE612`, boot `acc75220` | Three cores ready and short silence playback; capture START failed with `EBUSY`, zero captured bytes | Failed capture test; AFE 0.1.25 corrects duplicate host activation but still needs fresh-boot capture/duplex qualification. |

Local Linux 7.3 speaker routing/tuning results and the public PipeWire graph
have separate validation boundaries. Neither qualifies the DSP candidate.

## Lifetime and diagnostic limits

DSP publication retains operating DRAM, AFE SRAM and module/runtime-PM
references. A task ACK, STOP or IRQ disable does not prove whole-core DMA
quiescence. Device-bound v4 clients reserve the selected provider before DSP
publication and add PM dependency ordering and retained-sleep votes. Their
v2-compatible upload may release a consumed temporary image buffer after a
canonical successful upload; that does not release the DSP lifetime
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
