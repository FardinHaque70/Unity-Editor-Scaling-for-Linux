# Beta validation

## Bridge inherited from prototype-v5.2

-109 library regression tests passed, including popup repeated configure,
 window-list lifecycle, cursor, viewport, output and input protocol tests.
- Local interactive testing: CachyOS, KWin6.8.2 Wayland, NVIDIA RTX4080,
 Unity6000.3.27f2, 3840x2160 display at145% desktop scale.
-100-point ruler blocks measured150px at150% and160px at160%.
- User confirmed menu proportions, click input, orbit, Transform label dragging,
 cursor size/theme, and (after final repairs) small menus and dock/undock.
- One earlier prototype exit was not explained or reproduced in a27-minute traced
 follow-up; it is not being represented as a proven crash-free implementation.

## Standalone application

The standalone application was installed into the real user account. A disposable
project launched through the Editor-wide wrapper, compiled its Editor script,
reported pixelsPerPoint2, UI150%, cursor backing72, and one native managed window,
and exited0. The helper and private display were cleaned up afterward.

A real uninstall restored the original Editor's exact SHA256, inode and mode;
configuration remained intact. Reinstall succeeded. Integration tests also cover
argv forwarding, utility bypass, fallback, update conflicts and guarded restore.
Installer failure-injection tests cover transactional rollback and owned-file /
symlink / manifest validation.

Native EditorApplication.OpenProject was tested with a replacement process.
The replacement retained the private display, reported the same150% settings,
and completed normal shutdown. The runner waits for matching replacement Editor
processes before stopping its helper. Original-process teardown returned SIGSEGV
with !gAlreadyClosing / Error relaunching Unity / s_EditorUserBuildSettings assertions.
Control experiments reproduced the same original-process assertion with the
unwrapped executable on both the bridge and native host DISPLAY:0 (PPP1). This
rules out the wrapper filename and bridge as prerequisites for that test failure.
It does not establish that every project-switch workflow has been validated.
Replacement exit code is not available to the supervisor after native reparenting;
the metadata records that limitation instead of inventing an exit status.

GTK smoke and focused behavior tests use isolated settings/fixtures. Native
Wayland captures checked the actual app layout. Latest interface behavior is
explicit scan, expandable Editor rows, one numeric percentage control, automatic
saving, visible collapsed scale and pending-edit confirmation.

The final complete standalone suite passed87 tests with no skips on the real
graphical session (UNITY_SCALE_TEST_GUI=1 and GSETTINGS_BACKEND=memory).
The GUI was also checked with the standalone non-presenting smoke command.
The final disabled-label simplification passed all6 focused GUI-state tests.
The generated native release was extracted into a fresh directory, installed to
a separate prefix, executed through its installed entry point, and uninstalled
successfully. The real installation and user settings remained independent.
Visible Unity-related menu entries were verified as Unity Hub and Unity Scale.
Unit tests are not substitutes for multi-machine graphical validation. Fake Editor
fixtures test process and restore behavior without changing real installations.
The release CI workflow is prepared locally; no external CI run is claimed.

## Release scope

Local helper ABI: glibc2.43. Rebuild on the target distribution, or use a verified
older-ABI CI artifact once available. The GTK interface needs GTK4.10/libadwaita1.4.
Broader compositor/GPU/multi-monitor and additional Unity-version testing remains
outstanding. Existing passing measurements belong to the described machine.
