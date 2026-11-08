# How scaling works

The AppImage installs one managed image under `~/.local/share/unity-editor-scaling-for-linux`, a `~/.local/bin/unity-scale` command, and an application-menu entry. Schema-2 preferences live in `~/.config/unity-editor-scaling-for-linux/settings.json`, keyed by the Editor's canonical executable path. The standard absolute XDG directory overrides are respected. Projects using that Editor share its setting. Preferences are independent of both projects and AppImage mounts.

Setup also connects detected, supported Editors, even when Custom scale is off. In each connected installation it:

- Preserves the original executable as `Editor/.Unity.unity-scale-original`, beside its existing `Data` directory.
- Replaces the usual `Editor/Unity` entry with a small compiled launcher, so existing Unity Hub launches enter that launcher.
- Adds `Editor/.unity-editor-scaling/`, containing the prebuilt `native-v2.so`, `wrapper-v2` and schema-2 `activation.json`.

The `product-profile-v2` runtime is relocatable across supported installations: installation-specific paths are validated from the activation record rather than compiled into the binary. The record binds the public Editor path, preserved original, settings file, owner, exact hashes and original file identity. Launcher and constructor checks refuse inconsistent, foreign or symlinked activation data. Original executable and instruction-byte guards still apply before hooks are installed. No compiler runs during end-user setup.

**The original executable's bytes stay intact on disk. With Custom scale enabled, the native library patches selected Unity functions in the running process's memory.** These are changes to Unity's internal platform and rendering code, not a public Unity extension API.

Project files, packages, Hub configuration, licenses, and desktop display settings are left unchanged. The app does not install a private Xwayland server or input-forwarding service. Unity uses the desktop's existing X11/Xwayland display.

## Scaling, rendering, and input

1. **Load before Unity starts.** The launcher verifies the preserved executable and native library, then executes Unity with the original argument vector. Linux's `LD_PRELOAD` mechanism loads the library before normal application startup. The library reads that Editor's saved choice once.

2. **Convert between UI points and window pixels.** At 150%, the shared factor is `1.5`: 1,000 Unity UI points occupy 1,500 window pixels. Hooks report this factor to Unity, divide incoming window geometry by it, and multiply outgoing size/position requests by it. Important layout paths retain fractional point sizes and project shared panel edges consistently to reduce rounding gaps.

3. **Keep drawing at the actual window resolution.** Separate hooks use GTK's accepted pixel allocation for graphics-buffer dimensions and the actual backing size for rendering viewports. Unity lays out a larger interface while drawing into the window's full pixel buffer. A view-allocation watcher queues a normal future Unity repaint when the accepted size differs from its backing buffer; it does not draw synchronously inside GTK's allocation callback.

   OpenGL and Vulkan use the same guarded `GUIViewPlatform`/`GfxWindow` boundary in this exact Editor build. Buffer creation and viewport calls continue through Unity's graphics-device interface. The scaling backend does not intercept Vulkan commands or manage its swapchain, synchronization, or GPU resources. Renderer selection remains with Unity's project settings or launch arguments.

   Native repaint batches can retain a C++ view after an earlier callback closes its GTK widget. The paint wrapper skips a view only while a repaint batch is active and both the native closing flag is set and its GTK widget is null. This prevents using the destroyed drawable. Null-widget previews without the closing flag, views with a widget, and paints outside a batch keep their existing dispatch. This check queues no work and adds no event loop or polling.

4. **Map input into the same coordinate space.** Pointer, button, scroll-position, drag, screen-origin, and popup-position paths convert coordinates to match the scaled layout. At 150%, a pointer position of 750 window pixels becomes 500 Unity points. Button payload patches preserve fractional positions at the relevant Unity event boundary; native GTK events remain available to GTK's own menus and event handling.

5. **Size GTK menus separately.** Custom mode sets process-local `GDK_SCALE=1`, `GDK_DPI_SCALE=1`, and `GDK_BACKEND=x11`, so GTK does not add another scale multiplier. Before the first menubar is created, it sets GTK font DPI to `96 × factor`—144 DPI at 150%. This setting also affects other native GTK widgets in that process. Geometry handling accounts for the measured menubar height and converts popup anchors back to window coordinates.

The factor stays fixed for that Unity process. **Restart Unity after changing a setting.** Saving preferences does not rescale an existing Editor.

With **Custom scale off**, Unity receives its inherited GTK/GDK environment and no scaling hooks are installed. The neutral library can remain loaded so a later Open Project child process can read a fresh preference. The custom percentage is remembered. Explicit **Custom 100%** still enables the custom paths and GTK DPI policy, so it is distinct from Unity default.

## Source

The launch and runtime implementation starts in [launcher.c](../native/launcher.c), [boot.c](../native/product/source/boot.c), and [startup.cpp](../native/product/source/startup.cpp).

## Application delivery and updates

The GUI's Python, GTK 4 and libadwaita libraries are bundled in the AppImage. Unity continues using its existing GTK 3 and graphics runtime. External processes receive the original host environment rather than the GUI's bundled library paths. The installed native library and activation record stay beside the Editor, so closing or moving the GUI image does not interrupt future Unity launches.

The manually invoked updater selects releases using GitHub's release list. It verifies a pinned Ed25519 key and a manifest binding version, channel, architecture, filename, byte length and SHA-256 before executing a new image. A self-contained helper outside the mounted image stages replacement on the same filesystem, retains one rollback image, and waits for the replacement's health acknowledgement. Installation prepares and validates native changes before promotion and requires affected Editors to be closed.

The runtime exposes an owner-thread, read-only snapshot interface for settled window/view geometry checks. It is intended for acceptance fixtures; production scaling does not poll this interface or run an additional monitoring loop. A reported scale or successful snapshot is not by itself evidence of correct presented content or physical input.
