# Validation and development

## Tested setup

Tested on my **CachyOS system with KDE Plasma on Wayland and a 28-inch 4K monitor**. **150% custom Editor scale looks right to me** on this setup; your preferred size may differ.

**GNOME and other desktop environments have not been tested.** The current native backend checks for KDE Wayland and refuses custom scaling on other sessions. Help extending compatibility, testing and verifying it, and reporting results would be very much appreciated.

Please [open an issue](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/issues) with your distribution, desktop environment/version, Wayland or X11 session, GPU/driver, monitor size/resolution, desktop scale, Unity version, and selected Editor scale. Describe what worked and any problems with rendering, input, menus, resizing, or docking.

## Runtime evidence and limits

Local development records for the earlier `product-profile-v1` delivery at **150%** include 30 physical target clicks with matching press/release counts, one context-menu selection, user-confirmed window resizing, Inspector scrolling and Scene navigation, captured Scene/Game/Inspector content through window recreation, and normal exit. Separate **160%** runs exercised repeated window creation, odd-size resizing, reload, rendered content, and sampled allocation/backing agreement. These are bounded observations on the target setup, not validation of every workflow or percentage.

The AppImage candidate introduces relocatable `product-profile-v2` activation and a bundled GUI runtime while retaining the scaling calculations. Earlier acceptance is useful regression evidence but does not establish acceptance of the newly packaged artifact. Release-specific records must identify the tested AppImage SHA-256, clean-host artifact checks, migration/update results, private Unity rendering/input checks and performance measurement limits. Publication remains pending those checks.

Physical docking, mixed-DPI monitor transitions, other Unity builds, other compositors/renderers, representative production projects, and performance or input/presentation latency have not been established by this validation. Resize stress also requests managed repaints, so it does not isolate the allocation watcher's contribution. The accepted 100–200% range is not a guarantee that every value works correctly.

Exact executable hashes and instruction-byte guards are checked before hooks are installed. Unsupported sessions, known unsupported renderer flags, and additional foreign `LD_PRELOAD` libraries refuse custom scaling. Renderer admission checks launch flags; it does not query the active GPU renderer before startup. A refusal before patching can leave Unity running without custom scaling; launcher identity failures stop launch, and installation failures after native code changes terminate the process. A saved preference alone is not evidence that scaling applied.

## Local v2 candidate checks — 8 November 2026

Private host-built v2 components were compared with an untouched copy of the same Unity executable after resolving a host NVIDIA driver/library mismatch by rebooting. Stock, Unity default and Custom **100/150/160/200%** completed the scripted workflow: actual floating Scene/Game/Inspector captures, outer-window resizing, domain reload/window recreation, a generated Terrain plus 576 cubes, Play-mode entry/exit, and normal process exit with code 0. This exercises a bounded disposable workload, not a representative production project or the final AppImage.

Initial snapshots at 150/160% included transient one-pixel allocation/backing differences. A follow-up at 100/150/160% took **40 successful owner-thread snapshots per scale, 120 total**, spanning resized and generated-scene states; every view in those samples matched its accepted GTK allocation and scale. These readbacks establish allocated geometry at the sampled boundaries, not completed GPU presentation or physical-input accuracy. Actual window captures provide separate rendering evidence. The physical click/menu/resize confirmations above still belong to v1 and must be repeated with the shipped artifact.

Single-run smoke timings for stock versus Custom 150% were respectively: launch to fixture ready **8.121/8.123 s**, enter Play **2.414/2.415 s**, exit Play **0.604/0.605 s**, and close request to process exit **23.204/22.900 s**. Launch includes fixture bootstrap/import; shutdown includes Unity's own teardown. Managed Scene GUI repaint callback intervals were recorded separately and are not GPU/compositor frame pacing. These observations are not a controlled or repeated performance benchmark and do not establish equal performance or input latency. The local evidence groups are `product-v2-reboot-2026-11-08` and `product-v2-rounding-repeat-2026-11-08`; final artifact acceptance remains outstanding.

## Development checks

From the source directory, run:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

`qa/run_checks.py` exercises the settings UI on isolated GTK Broadway. The native package's checks use generated payloads, mock native callees, or a tiny non-Unity host; passing them does not prove Unity rendering or physical input. The builder verifies the [native source manifest](../native/product/source-manifest.json). End-user installation verifies the prebuilt runtime and its activation record without compiling native code.
