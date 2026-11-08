# Unity Editor Scaling for Linux

Make Unity Editor easier to read on high-DPI Linux displays, with a scale setting shared by every project using that Editor.

**Development prerelease · Unity 6000.3.27f2 · Linux x86_64 · KDE Wayland · OpenGL**

![Standalone settings app with Custom scale set to 150%](https://raw.githubusercontent.com/FardinHaque70/unity-editor-ui-scalar-for-linux/main/docs/screenshots/standalone-app.png)

## Tested setup

| System | Display | Preferred Editor scale |
| --- | --- | --- |
| CachyOS, KDE Plasma on Wayland | 28-inch 4K monitor | 150% |

Other setups and percentages need more testing. **GNOME and other desktop environments are untested; the current backend only accepts KDE Wayland.** Help extending support, testing, and [reporting results](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/issues) would be very much appreciated.

Only the exact supported Unity executable is accepted. Unity must use OpenGL; local trials used `-force-glcore`. See [compatibility and validation](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/blob/main/docs/VALIDATION.md).

## How it works

Setup preserves the original Unity executable, puts a small launcher at its usual path, and adds a native library. With Custom scale enabled, that library loads through `LD_PRELOAD` and patches selected Unity functions **in process memory**. The original executable's bytes remain intact on disk.

The hooks coordinate UI layout, full-resolution rendering, mouse coordinates, and GTK menus. At 150%, 1,000 UI points occupy 1,500 window pixels. Projects and desktop settings stay unchanged.

[Read the technical explanation →](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/blob/main/docs/ARCHITECTURE.md)

## Install and use

Install the [dependencies](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/blob/main/docs/INSTALL.md#requirements), close Unity and the settings app, then run from the source directory:

```sh
/usr/bin/python3 install.py --check
/usr/bin/python3 install.py
```

1. Open **Unity Editor Scaling for Linux** from your application menu.
2. Select an Editor, enable **Custom scale**, and choose **100–200%**.
3. Wait for **Saved**, then **restart Unity** through its usual launcher.

Turn Custom scale off to use Unity default after restarting. The app reports saved settings and launcher status, not the effective scale of a running Editor.

**Restore the original launcher before updating or removing a connected Editor.** See [installation, restoration, and updates](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/blob/main/docs/INSTALL.md).

---

[Architecture](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/blob/main/docs/ARCHITECTURE.md) · [Validation and development checks](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/blob/main/docs/VALIDATION.md) · [Report an issue](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/issues)

Independent and unofficial. Unity Editor and Hub are not included. [MPL 2.0](LICENSE) · [NOTICE](NOTICE)
