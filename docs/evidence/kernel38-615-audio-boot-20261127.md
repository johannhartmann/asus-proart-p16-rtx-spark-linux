# Kernel38 and NVIDIA 615 after the 27 November restart

The restart entered Limine (`Boot0002`) and booted kernel
`7.2.8-38-rtx-spark-npu` from Btrfs subvolume `@` with NVIDIA
`615.78.08`. UEFI still lists the [prepared 620 candidate](nvidia620-isolated-root-staging.md#one-attended-native-qualification-session)
as `Boot0004`, outside the regular boot order. `BootNext` was unset.
This is a 615 baseline with the audio boot policy active. Native 620
qualification remains pending.

## Audio boot and streaming

The kernel command line contains all five DSP boot/routing options and
blacklists `snd_sof_mt8901`. All three `NVDA830[123]:00` devices bound
to `n1x-adsp` and reported `ready=1`, `error=0`, and `asoc_ready=1`.
ALSA enumerated `mt8901-soundwire`. PipeWire exposed the internal
speakers and microphone array.

A bounded stereo S16_LE microphone request at 48 kHz delivered all
192,000 requested bytes, including 183,482 nonzero bytes. The sample
limit invocation returned exit code 1 and the captured data was
discarded. The speaker test timed out using both raw input and a finite
WAV file. In two samples one second apart, the running 48 kHz stereo
S24_LE ALSA stream held `hw_ptr=0` and `appl_ptr=1536`. The HiFi1
DSP showed `pcm_running=1`, three buffer write publications, and zero
PCM notifications and counter progress in both samples. The DSP boot
and capture data path were observed. Internal speaker playback remains
unqualified. The next comparison should check hardware pointer and DSP
period progress on 620 with the same audio routes.

## NVIDIA and Chrome

The installed `ffmpeg-n1x-video 9.0.2-7` probe again failed for H.264,
HEVC and AV1 at `OpenEncodeSessionEx` with error 21. This matches the
[previous 615 result](n1x-media-20261118/installed-nvenc-package7-kernel38/installed-nvenc.json).

Chrome had installed the external Meet extension in the normal profile
with no recorded disable reason. The [normal launcher](n1x-media-20261120/chrome-default-meet-launcher.md)
started that profile and the Vulkan VA-API driver reported an H.264
encode queue. Driver initialization alone leaves live Meet encode and CPU
usage unqualified.

At 07:16:17 CET, while Chrome was starting, Lockdep reported a possible
cycle through NVIDIA GPU I2C device registration, NVIDIA UVM channel and
mapping paths, `mmap_lock`, and `kernfs_rwsem`. The acquisition that
triggered the report was a page fault from a sysfs directory read. The
system remained responsive. The trace does not establish that Chrome's
codec extension caused the cycle or that the audio stall is related.
Physical suspend/resume remains pending.
