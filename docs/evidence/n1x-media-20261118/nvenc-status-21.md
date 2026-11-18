# NVENC status 21 in the tested SDK headers

The installed FFmpeg and independent C/OpenGL probes fail
`NvEncOpenEncodeSessionEx` with numeric status **21** on NVIDIA 615.78.08.
Compiling a trivial constant-printing program against both locally pinned
`nv-codec-headers` 12.2.72.0 and 13.1.15.0 confirms that status 21 is
`NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY` in both header sets. The adjacent SDK
comment describes a client attempting a feature unavailable for the current
license type; `NV_ENC_ERR_GENERIC` is 20 and `NV_ENC_ERR_UNIMPLEMENTED` is 22.

This identifies the returned status, not the driver-internal cause. H.264,
HEVC and AV1 all fail before encoder initialization, and the same status
appears with CUDA and OpenGL devices. A separate ARM64 RTX 5050 report found
working NVENC with 610.57.04 and status 21 with 615.71.09. That report and
the enum name do not establish whether the N1X failure is a license policy,
driver regression, firmware mismatch or another platform gate. Testing a
fully matched newer driver stack remains the next discriminating experiment.

The repository's [CUDA session probe](../../../scripts/probe-nvenc-session.c)
now prints the symbolic name alongside the unchanged numeric status. It built
with `-Wall -Wextra -Werror` against both pinned header sets and ran on the
native `7.2.8-37-rtx-spark-npu` boot with NVIDIA 615.78.08. API 12.2 reported
`header_api_version=0x200000c`; API 13.1 reported `0x100000d`. Both queried
`driver_max_api_version=0xd1`, created the function list successfully, then
printed `open_session_status=21` and
`open_session_status_name=NV_ENC_ERR_INCOMPATIBLE_CLIENT_KEY` before exiting
5 as expected. No new kernel warning appeared in this probe window.
