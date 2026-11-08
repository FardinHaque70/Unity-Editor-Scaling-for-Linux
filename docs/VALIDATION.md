# Validation and development

See the [Editor-version and desktop-environment checklists](COMPATIBILITY.md) for the current support matrix.

## Tested setup

Tested on my **CachyOS system with KDE Plasma on Wayland and a 28-inch 4K monitor**. **150% custom Editor scale looks right to me** on this setup; your preferred size may differ.

**GNOME and other desktop environments have not been tested.** The current native backend checks for KDE Wayland and refuses custom scaling on other sessions. Help extending compatibility, testing and verifying it, and reporting results would be very much appreciated.

Please [open an issue](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/issues) with your distribution, desktop environment/version, Wayland or X11 session, GPU/driver, monitor size/resolution, desktop scale, Unity version, and selected Editor scale. Describe what worked and any problems with rendering, input, menus, resizing, or docking.

## Runtime evidence and limits

Local development records for the current native source at **150%** include 30 physical target clicks with matching press/release counts, one context-menu selection, user-confirmed window resizing, Inspector scrolling and Scene navigation, captured Scene/Game/Inspector content through window recreation, and normal exit. Separate **160%** runs exercised repeated window creation, odd-size resizing, reload, rendered content, and sampled allocation/backing agreement. These are bounded observations on the target setup, not validation of every workflow or percentage.

Physical docking, mixed-DPI monitor transitions, other Unity builds, other compositors/renderers, heavy workloads, and performance or input/presentation latency have not been established by this validation. Resize stress also requests managed repaints, so it does not isolate the allocation watcher's contribution. The accepted 100–200% range is not a guarantee that every value works correctly.

Exact executable hashes and instruction-byte guards are checked before hooks are installed. Unsupported sessions, known unsupported renderer flags, and additional foreign `LD_PRELOAD` libraries refuse custom scaling. Renderer admission checks launch flags; it does not query the active GPU renderer before startup. A refusal before patching can leave Unity running without custom scaling; launcher identity failures stop launch, and installation failures after native code changes terminate the process. A saved preference alone is not evidence that scaling applied.

## 100% / 160% screenshot comparison

Fresh captures on 8 November 2026 use the exact supported Editor, OpenGL, the same saved scene and built-in Default layout, and equal measured window dimensions. Both runs use **Custom scale**: measured pixels per point are 1.0 and approximately 1.6. Desktop scaling is unchanged. The images are original KWin window captures, with no resizing or retouching; [capture metadata](screenshots/comparison.json) records hashes and dimensions. These are visual checks, not physical-input or performance benchmarks.

The published 160% capture visibly includes `MissingReferenceException: UnityEditor.Toolbar` after the test helper programmatically reloaded the default layout. Both pictured runs verified the requested scale and exited normally, but the exception remains unresolved; whether it is caused by the backend or capture procedure has not been isolated. A follow-up attempt with the layout supplied before startup stalled before fixture readiness and was stopped; it is not counted as a pass. The comparison demonstrates the size change, not error-free 160% operation.

## Development checks

From the source directory, run:

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

`qa/run_checks.py` exercises the settings UI on isolated GTK Broadway. The native package's checks use generated payloads, mock native callees, or a tiny non-Unity host; passing them does not prove Unity rendering or physical input. The installer verifies the bundled [native source manifest](../native/product/source-manifest.json).
