# Unity Editor Scaling for Linux

[![Download AppImage](https://img.shields.io/badge/Download-x86__64_AppImage-blue)](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/releases/download/v0.4.0-rc.1/Unity-Editor-Scaling-for-Linux-x86_64.AppImage)

**[v0.4.0-rc.1 prerelease is available](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/releases/tag/v0.4.0-rc.1).** See its scoped validation results and remaining limits. [Release notes](docs/releases/v0.4.0-rc.1.md) · [GitHub releases](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/releases)

Adjust Unity Editor's UI scale independently of your desktop. Each Editor has one Custom scale toggle and a **100–200%** control, shared by every project using that Editor.

[Compatibility](#compatibility) · [100% → 160% comparison](#unity-editor-100--160) · [Install](#install-and-use)

## Unity Editor: 100% → 160%

| Before — 100% | After — 160% |
| --- | --- |
| <a href="https://raw.githubusercontent.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/main/docs/screenshots/unity-before-100.png"><img src="https://raw.githubusercontent.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/main/docs/screenshots/unity-before-100.png" alt="Unity Editor at 100%" width="360"></a> | <a href="https://raw.githubusercontent.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/main/docs/screenshots/unity-after-160.png"><img src="https://raw.githubusercontent.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/main/docs/screenshots/unity-after-160.png" alt="Unity Editor at 160%" width="360"></a> |

Same Unity build, scene, default layout, and window size. Both use Custom scale; click either capture for full resolution. The 160% image contains an error from the capture test; normal 160% launch was subsequently reported working. See [test notes](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/blob/main/docs/VALIDATION.md#100--160-screenshot-comparison). [Capture details](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/blob/main/docs/screenshots/comparison.json).

## Standalone app

<img src="https://raw.githubusercontent.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/main/docs/screenshots/standalone-app.png" alt="Standalone settings app with Custom scale set to 150%" width="680">

## Compatibility

The native backend accepts one exact Unity executable build. The Editor installation must be owned and writable by your user, with no spaces or colons in its path. The AppImage itself can be in a path containing spaces. Root-owned Editors, other Unity builds, other desktops and live scaling are outside this release.

### Unity Editor versions

| Linux x86_64 Editor | Status |
| --- | --- |
| **6000.3.27f2 — exact supported binary** | ✅ Scoped 150% tests |
| Unity 6.0 / 6000.0.x | ⛔ Unsupported |
| Unity 6.1 / 6000.1.x | ⛔ Unsupported |
| Unity 6.2 / 6000.2.x | ⛔ Unsupported |
| Other Unity 6.3 / 6000.3.x builds | ⛔ Unsupported |
| Other Unity 6 builds | ⛔ Unsupported |
| Unity 2022, 2021, and older | ⛔ Unsupported |

### Desktop environments

| Desktop / session | Status |
| --- | --- |
| **KDE Plasma / Wayland on CachyOS** | ✅ Tested |
| KDE Plasma / Wayland on other distributions | ⬜ Allowed, untested |
| KDE Plasma / X11 | ⛔ Blocked, untested |
| GNOME / Wayland or X11 | ⛔ Blocked, untested |
| Hyprland / Wayland | ⛔ Blocked, untested |
| Cinnamon, including Linux Mint Cinnamon | ⛔ Blocked, untested |
| MATE / Xfce, including Linux Mint editions | ⛔ Blocked, untested |
| Sway and other Wayland compositors | ⛔ Blocked, untested |

[Detailed checklists and validation scope](docs/COMPATIBILITY.md). Help extending support and [reporting test results](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/issues) is appreciated.

Local development used CachyOS, KDE Plasma Wayland, an NVIDIA RTX 4080 and a 4K display, with desktop scale at 145% and Unity at 150%. Other hardware and workloads need further testing. See [validation and limitations](docs/VALIDATION.md).

The tool changes UI scale. Unity and the developer retain control of graphics APIs, render pipelines, project settings and launch arguments. OpenGL Core and Vulkan have local test evidence; that is coverage information, not a renderer restriction. When the native adapter cannot safely apply scaling before patching, it skips custom scaling and lets Unity continue.

## Install and use

Download the AppImage above, make it executable and open it:

```sh
chmod +x Unity-Editor-Scaling-for-Linux-x86_64.AppImage
./Unity-Editor-Scaling-for-Linux-x86_64.AppImage
```

The AppImage includes Python, PyGObject, GTK 4, libadwaita and prebuilt native components. You do not need development packages or a compiler. It uses your existing Unity installation and graphics drivers. If mounting is unavailable, run it with `--appimage-extract-and-run`.

1. Save your work and close Unity before initial setup.
2. Open **Unity Editor Scaling for Linux** and select your Editor.
3. Turn on **Custom scale**, choose a percentage and wait for **Saved**.
4. Launch Unity through Unity Hub or your usual launcher. Restart Unity after later scale changes.

First launch creates one managed AppImage, the `unity-scale` command and an application-menu entry. Preferences remain outside the image. You can close the settings app afterward; scaling does not depend on the GUI staying open.

Turn **Custom scale off** for Unity default on the next launch. This retains the connection and remembers your custom percentage. Custom **100%** still uses the custom scaling paths and differs from Unity default. The app reports saved settings and connection status; it does not measure the running Editor's effective scale.

## Updates and removal

Use **⋮ → Check for Updates → Download and Restart**. Checks happen only when requested. Downloads are verified against a pinned Ed25519 signing key and SHA-256 before execution. Prerelease builds can receive newer prereleases or stable versions; stable builds receive stable versions. Close connected Editors before updating their native components.

**Restore each connected Editor before updating/removing that Editor or uninstalling this app:**

```sh
unity-scale restore --editor /absolute/path/to/Editor/Unity
```

Keep the original executable backup until restoration succeeds. [Installation, recovery and file locations](docs/INSTALL.md) explain the managed files and removal procedure.

## Native scaling

Setup preserves Unity's original executable and places a small launcher at its usual path. With Custom scale enabled, a native library patches guarded functions **in Unity's process memory** to coordinate layout, window geometry, full-resolution rendering, input and menu coordinates. It uses the desktop's existing Xwayland; no private display server or input bridge is installed. Projects and desktop display settings stay unchanged.

Scale is fixed for each Unity process. There is no claim of universal performance equivalence or compatibility. [Architecture](docs/ARCHITECTURE.md) · [Validation](docs/VALIDATION.md) · [Report an issue](https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux/issues)

Independent and unofficial. Unity Editor and Hub are not included. [MPL 2.0](LICENSE) · [Notices and bundled dependencies](NOTICE)
