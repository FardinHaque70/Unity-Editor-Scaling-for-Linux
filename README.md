# Unity Editor Scaling for Linux

Adjust Unity Editor UI size on high-DPI Linux displays with a per-Editor scale setting. **0.3.0.dev1 is a development prerelease**, with scoped local validation at 150% and limited coverage at other percentages.

The current backend targets one exact **Unity 6000.3.27f2 Linux x86_64** executable on **KDE Wayland**, with Unity using **GTK 3 over X11/Xwayland and OpenGL**. The launcher does not select a renderer; the local trials explicitly used `-force-glcore` in Unity's launch arguments. It uses a native library loaded into Unity at startup. Compatibility depends on the executable's SHA-256, not just its version label:

```text
d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec
```

## What gets installed and changed

The installer adds the settings app under `~/.local/share/unity-editor-scaling-for-linux`, a `~/.local/bin/unity-scale` command, and an application-menu entry. Preferences live in the installed app's `sandbox/config/unity-scale/settings.json`, keyed by the Editor's canonical executable path. Projects using that Editor share its setting.

Setup also connects detected, supported Editors, even when Custom scale is off. In each connected installation it:

- Preserves the original executable as `Editor/.Unity.unity-scale-original`, beside its existing `Data` directory.
- Replaces the usual `Editor/Unity` entry with a small compiled launcher, so existing Unity Hub launches enter that launcher.
- Adds `Editor/.unity-editor-scaling/`, containing the native library, launcher copy, and ownership/restoration receipt.

**The original executable's bytes stay intact on disk. With Custom scale enabled, the native library patches selected Unity functions in the running process's memory.** These are changes to Unity's internal platform and rendering code, not a public Unity extension API.

Project files, packages, Hub configuration, licenses, and desktop display settings are left unchanged. The app does not install a private Xwayland server or input-forwarding service. Unity uses the desktop's existing X11/Xwayland display.

## How scaling works

1. **Load before Unity starts.** The launcher verifies the preserved executable and native library, then executes Unity with the original argument vector. Linux's `LD_PRELOAD` mechanism loads the library before normal application startup. The library reads that Editor's saved choice once.

2. **Convert between UI points and window pixels.** At 150%, the shared factor is `1.5`: 1,000 Unity UI points occupy 1,500 window pixels. Hooks report this factor to Unity, divide incoming window geometry by it, and multiply outgoing size/position requests by it. Important layout paths retain fractional point sizes and project shared panel edges consistently to reduce rounding gaps.

3. **Keep drawing at the actual window resolution.** Separate hooks use GTK's accepted pixel allocation for graphics-buffer dimensions and the actual backing size for rendering viewports. Unity lays out a larger interface while drawing into the window's full pixel buffer. A view-allocation watcher queues a normal future Unity repaint when the accepted size differs from its backing buffer; it does not draw synchronously inside GTK's allocation callback.

4. **Map input into the same coordinate space.** Pointer, button, scroll-position, drag, screen-origin, and popup-position paths convert coordinates to match the scaled layout. At 150%, a pointer position of 750 window pixels becomes 500 Unity points. Button payload patches preserve fractional positions at the relevant Unity event boundary; native GTK events remain available to GTK's own menus and event handling.

5. **Size GTK menus separately.** Custom mode sets process-local `GDK_SCALE=1`, `GDK_DPI_SCALE=1`, and `GDK_BACKEND=x11`, so GTK does not add another scale multiplier. Before the first menubar is created, it sets GTK font DPI to `96 × factor`—144 DPI at 150%. This setting also affects other native GTK widgets in that process. Geometry handling accounts for the measured menubar height and converts popup anchors back to window coordinates.

The factor stays fixed for that Unity process. **Restart Unity after changing a setting.** Saving preferences does not rescale an existing Editor.

With **Custom scale off**, Unity receives its inherited GTK/GDK environment and no scaling hooks are installed. The neutral library can remain loaded so a later Open Project child process can read a fresh preference. The custom percentage is remembered. Explicit **Custom 100%** still enables the custom paths and GTK DPI policy, so it is distinct from Unity default.

## Install and use

Requirements: system Python 3.10+ with PyGObject, GTK 4.10+, and libadwaita 1.4+ for the settings app; C/C++ compilers, `pkg-config`, and GTK 3, json-c, and OpenSSL development files to build the native components. An existing supported Unity installation must be writable by your user. Its path must contain no whitespace or colon. Dependencies are provided by your distribution; the installer does not download them.

Close the settings app and the target Editor. From the source directory:

```sh
/usr/bin/python3 install.py --check
/usr/bin/python3 install.py
```

`--check` verifies required sources, the native source manifest, and installation paths; it does not compile the backend or establish runtime compatibility. Installation prepares compiler outputs before changing installed files. It does not launch Unity. Supported Editors added later can be connected by rerunning the installer. Unsupported Editors may appear in the app and retain preferences, but those preferences do not apply scaling.

Open **Unity Editor Scaling for Linux** from the application menu. Select an Editor, enable **Custom scale**, and enter a whole percentage from **100% to 200%** or use the slider. Valid changes save automatically. Wait for **Saved**, then restart Unity through its usual launcher. The settings app can be closed afterward.

The status reports saved preferences and a verified launcher connection; it does not measure the effective scale or confirm a presented frame in a running Editor. Running `./launch.sh` from a source checkout uses that copy's separate preferences; use the installed app to control the installed connection.

## Restore and update

Turning Custom scale off selects Unity default on the next launch; it leaves the launcher connection installed. To remove the connection, close that Editor and run from the source directory:

```sh
/usr/bin/python3 install.py --restore-editor /absolute/path/to/Editor/Unity
```

Restore before updating or removing a connected Editor. Restoration verifies ownership and the preserved original, and refuses unrelated file changes instead of overwriting them. Keep the backup and receipt until restoration succeeds. Updating the settings app preserves its preferences and does not replace an already connected native backend; restore and rerun setup to rebuild that connection. There is no app-uninstall command in this version; restore every connected Editor before removing the app's user-local files.

## Validation and limits

Local development records for the current native source at **150%** include 30 physical target clicks with matching press/release counts, one context-menu selection, user-confirmed window resizing, Inspector scrolling and Scene navigation, captured Scene/Game/Inspector content through window recreation, and normal exit. Separate **160%** runs exercised repeated window creation, odd-size resizing, reload, rendered content, and sampled allocation/backing agreement. These are bounded observations on the target setup, not validation of every workflow or percentage.

Physical docking, mixed-DPI monitor transitions, other Unity builds, other compositors/renderers, heavy workloads, and performance or input/presentation latency have not been established by this validation. Resize stress also requests managed repaints, so it does not isolate the allocation watcher's contribution. The accepted 100–200% range is not a guarantee that every value works correctly.

Exact executable hashes and instruction-byte guards are checked before hooks are installed. Unsupported sessions, known unsupported renderer flags, and additional foreign `LD_PRELOAD` libraries refuse custom scaling. Renderer admission checks launch flags; it does not query the active GPU renderer before startup. A refusal before patching can leave Unity running without custom scaling; launcher identity failures stop launch, and installation failures after native code changes terminate the process. A saved preference alone is not evidence that scaling applied.

For source checks, run `/usr/bin/python3 -m unittest discover -s tests -v`. `qa/run_checks.py` exercises the settings UI on isolated GTK Broadway. The native package's checks use generated payloads, mock native callees, or a tiny non-Unity host; passing them does not prove Unity rendering or physical input. The installer verifies the bundled [native source manifest](native/product/source-manifest.json). The launch and runtime implementation starts in [launcher.c](native/launcher.c), [boot.c](native/product/source/boot.c), and [startup.cpp](native/product/source/startup.cpp).

Independent and unofficial; Unity Editor and Hub are not included. Distributed under [MPL 2.0](LICENSE). See [NOTICE](NOTICE).
