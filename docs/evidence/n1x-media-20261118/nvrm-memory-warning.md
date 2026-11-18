# NVRM allocation warning during installed HEVC matrix

At 2026-11-18 11:02:30 Europe/Berlin, the kernel logged two NVIDIA
`NV_ERR_NO_MEMORY` failures in `_memdescAllocInternal`; the exact lines are in
[`nvrm-memory-warning.log`](nvrm-memory-warning.log). The event occurred while
the installed matrix was testing HEVC 4:4:4 10-bit mpv Vulkan playback
(11:02:28–11:02:32). That application still reported `vulkan[p410]` and EOF.
The separately launched 4:2:2/AAC player had finished at 11:02:08, so the two
media tests did not overlap at the warning time. A vLLM EngineCore process was
using roughly 34 GiB of GPU memory when checked afterward; the allocation
failure cannot be attributed to a process from the journal lines alone.

The same 4:4:4 10-bit case was repeated alone at 11:05:13–11:05:19 with
[`--case 444:10`](hevc44410-repeat/hevc-pro-matrix.json). CUVID pixels matched
software, mpv again selected `vulkan[p410]` and reached EOF. No new NVRM, Xid,
IOMMU or GPU-fault lines appeared in the boot kernel journal from 11:04:30
through the end of that repeat. One clean repeat does not establish sustained
memory stability. This warning keeps the longer/concurrent workload gate open.
