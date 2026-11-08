# Validation and development

## Tested setup

Tested on my **CachyOS system with KDE Plasma on Wayland and a 28-inch 4K monitor**. **150% custom Editor scale looks right to me** on this setup; your preferred size may differ.

**GNOME and other desktop environments have not been tested.** The current native backend checks for KDE Wayland and refuses custom scaling on other sessions. Help extending compatibility, testing and verifying it, and reporting results would be very much appreciated.

Please [open an issue](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/issues) with your distribution, desktop environment/version, Wayland or X11 session, GPU/driver, monitor size/resolution, desktop scale, Unity version, and selected Editor scale. Describe what worked and any problems with rendering, input, menus, resizing, or docking.

## Runtime evidence and limits

Local development records for the earlier `product-profile-v1` delivery at **150%** include 30 physical target clicks with matching press/release counts, one context-menu selection, user-confirmed window resizing, Inspector scrolling and Scene navigation, captured Scene/Game/Inspector content through window recreation, and normal exit. Separate **160%** runs exercised repeated window creation, odd-size resizing, reload, rendered content, and sampled allocation/backing agreement. These are bounded observations on the target setup, not validation of every workflow or percentage.

The AppImage candidate introduces relocatable `product-profile-v2` activation and a bundled GUI runtime while retaining the scaling calculations. Earlier acceptance is useful regression evidence but does not establish acceptance of the newly packaged artifact. Release-specific records must identify the tested AppImage SHA-256, clean-host artifact checks, migration/update results, private Unity rendering/input checks and performance measurement limits. Publication remains pending those checks.

Physical docking, mixed-DPI monitor transitions, other Unity builds, other compositors, graphics APIs beyond the locally tested OpenGL/Vulkan paths, representative production projects, and performance or input/presentation latency have not been established by this validation. Untested graphics APIs are not blocked by the scaler. Resize stress also requests managed repaints, so it does not isolate the allocation watcher's contribution. The accepted 100–200% range is not a guarantee that every value works correctly.

Exact executable hashes and instruction-byte guards are checked before hooks are installed. Unsupported native sessions and additional foreign `LD_PRELOAD` libraries skip custom scaling before patching and let Unity continue. Renderer arguments are neither selected nor screened by the scaler: Unity owns their meaning and validation. Launcher identity failures still stop launch because the trusted original cannot be established, and failures after native code changes terminate the process because a partial installation cannot safely continue. A saved preference alone is not evidence that scaling applied.

## Vulkan validation — 8 November 2026

The host-built v2 bundle completed Vulkan runs with stock Unity, connected Default, and Custom 100%/150% on Unity 6000.3.27f2, KDE Wayland/Xwayland, RTX 4080 and NVIDIA 620.70.06. The disposable Built-in rendering fixture exercised floating Scene/Game/Inspector views, odd-size resizing, domain reload, generated Terrain plus 576 cubes, Play-mode entry/exit and normal exit code 0. Unity reported the Vulkan API and the expected Editor/UI Toolkit scale. This establishes bounded local compatibility, not validation of every rendering feature or pipeline.

The initial Vulkan trials used an earlier admission build. The current source leaves all renderer arguments to Unity. Its final AppImage acceptance is pending; the earlier bundle does not establish acceptance of the shipped artifact. The interrupted 160% trial, 200%, URP, physical input and performance remain outside that initial Vulkan evidence.

## Local v2 candidate checks — 8 November 2026

Private host-built v2 components were compared with an untouched copy of the same Unity executable after resolving a host NVIDIA driver/library mismatch by rebooting. Stock, Unity default and Custom **100/150/160/200%** completed the scripted workflow: actual floating Scene/Game/Inspector captures, outer-window resizing, domain reload/window recreation, a generated Terrain plus 576 cubes, Play-mode entry/exit, and normal process exit with code 0. This exercises a bounded disposable workload, not a representative production project or the final AppImage.

Initial snapshots at 150/160% included transient one-pixel allocation/backing differences. A follow-up at 100/150/160% took **40 successful owner-thread snapshots per scale, 120 total**, spanning resized and generated-scene states; every view in those samples matched its accepted GTK allocation and scale. These readbacks establish allocated geometry at the sampled boundaries, not completed GPU presentation or physical-input accuracy. Actual window captures provide separate rendering evidence. The physical click/menu/resize confirmations above still belong to v1 and must be repeated with the shipped artifact.

Single-run smoke timings for stock versus Custom 150% were respectively: launch to fixture ready **8.121/8.123 s**, enter Play **2.414/2.415 s**, exit Play **0.604/0.605 s**, and close request to process exit **23.204/22.900 s**. Launch includes fixture bootstrap/import; shutdown includes Unity's own teardown. Managed Scene GUI repaint callback intervals were recorded separately and are not GPU/compositor frame pacing. These observations are not a controlled or repeated performance benchmark and do not establish equal performance or input latency. The local evidence groups are `product-v2-reboot-2026-11-08` and `product-v2-rounding-repeat-2026-11-08`; final artifact acceptance remains outstanding.

## Development checks

From the source directory, run:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

`qa/run_checks.py` exercises the settings UI on isolated GTK Broadway. The native package's checks use generated payloads, mock native callees, or a tiny non-Unity host; passing them does not prove Unity rendering or physical input. The builder verifies the frozen instruction-guard sources and records all native source hashes; the [reviewed source manifest](../native/product/source-manifest.json) records the source package. End-user installation verifies the prebuilt runtime and its activation record without compiling native code.
