# P16 audio DSP boot profile

This small package adds the five kernel parameters used by the qualified
kernel36 native audio path to the **normal** Limine command line. It excludes
the placeholder `snd_sof_mt8901` claimant and enables P16 ADSP firmware,
retention sleep, AFE playback/capture and the SoundWire machine route.
The separate fallback command line remains unchanged.

Installing the package only installs the drop-in; it does not rebuild a UKI.
After installation, explicitly run `limine-mkinitcpio` for the selected P16
kernel, verify that the generated UKI contains these flags, then qualify its
next native boot. This keeps other kernel images byte-identical during a
candidate test.
