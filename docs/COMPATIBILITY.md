# Compatibility checklist

Last updated: **8 November 2026**. This tracks the **native scaling backend**; being able to open the settings app does not establish Editor scaling support.

Checked items have the evidence described beside them. **Blocked** means the current backend refuses that build or session. **Untested** means no compatibility result has been established.

## Unity Editor versions

All entries refer to Linux x86_64 Editors. The historical visual comparisons below used OpenGL. The current adapter preserves Unity's graphics API and render-pipeline choices; [validation](VALIDATION.md) identifies the OpenGL and Vulkan cases actually tested.

- [x] **6000.3.27f2, exact binary below** — supported. Scoped physical-input/window tests at 150%; 100% and 160% visual captures and earlier resize/rendering checks. The maintainer subsequently reported a normal 160% launch without errors. See [validation details](VALIDATION.md).
- [ ] **Unity 6.0 / 6000.0.x** — blocked; no compatibility adapter or runtime validation.
- [ ] **Unity 6.1 / 6000.1.x** — blocked; no compatibility adapter or runtime validation.
- [ ] **Unity 6.2 / 6000.2.x** — blocked; no compatibility adapter or runtime validation.
- [ ] **Other Unity 6.3 / 6000.3.x builds** — blocked; the verified 6000.3.27f2 adapter does not establish support for other patch releases.
- [ ] **Other Unity 6 builds** — blocked; no compatibility adapter or runtime validation.
- [ ] **Unity 2022, 2021, and older** — blocked; no compatibility adapter or runtime validation.

Supported original executable SHA-256:

```text
d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec
```

The backend patches private native functions using build-specific addresses, instruction recipes, and object layouts. Additional builds need validated adapters; removing the hash check does not add compatibility. Future checklist entries should identify an exact Editor version and executable hash.

## Desktop environments and sessions

These entries assume the supported Editor binary and native window adapter. The distribution alone does not determine compatibility.

- [x] **KDE Plasma / Wayland on CachyOS** — tested with the desktop's Xwayland display, a 28-inch 4K monitor, and the scoped checks below.
- [ ] **KDE Plasma / Wayland on other distributions** — admitted by the session check when dependencies are present; untested here.
- [ ] **KDE Plasma / X11** — blocked by the current Wayland-session requirement; untested.
- [ ] **GNOME / Wayland or X11** — blocked by the KDE-session requirement; untested.
- [ ] **Hyprland / Wayland** — blocked by the KDE-session requirement; untested.
- [ ] **Sway and other Wayland compositors** — blocked by the KDE-session requirement; untested.
- [ ] **Cinnamon, including Linux Mint Cinnamon** — blocked by the KDE-session requirement; untested.
- [ ] **MATE, including Linux Mint MATE** — blocked by the KDE-session requirement; untested.
- [ ] **Xfce, including Linux Mint Xfce** — blocked by the KDE-session requirement; untested.

Help implementing compatibility and verifying other environments is welcome. Changing a desktop environment name to bypass the check does not establish support.

## Scale and workflow coverage

- [x] **Custom 100%** — measured UI scale and a captured main Editor window; used as the visual baseline.
- [x] **Custom 150%** — scoped physical clicks, a context-menu selection, resizing, Inspector scrolling, Scene navigation, captured window recreation, and normal shutdown.
- [x] **Custom 160%** — measured UI scale and a captured main Editor window; separate scoped resize/rendering/reload checks. On 8 November 2026, the maintainer also reported a normal 160% launch without errors. Full physical-input coverage at 160% is untested.
- [ ] **Complete 100–200% coverage** — not established; accepting a percentage in settings is not proof that every workflow works at that value.
- [ ] **Physical docking and mixed-DPI monitor transitions** — not established.
- [ ] **Performance and input/presentation latency benchmarks** — not established.

The [100%/160% comparison](screenshots/comparison.json) records the capture-test toolbar exception separately from normal-startup reports, along with the scene identity, requested and measured scale, renderer, window dimensions, capture hashes, and normal exit. Screenshots show rendering; they do not verify physical input or performance.

## Report a result

[Open a compatibility report](https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux/issues/new) with:

- Exact Unity version, app commit/version, and original executable hash when available.
- Distribution, desktop environment/version, Wayland or X11, GPU/driver, and graphics renderer.
- Monitor size/resolution, desktop scale, and selected Editor scale.
- What you checked: startup, rendering, clicks/typing, menus, resize, docking, reload, Play mode, normal close, and restoration.
- Screenshots or reproduction steps for any failure. Distinguish untested actions from passed checks.

Add a checked entry only with a specific setup and recorded results. Generalize a version range only after its compatibility has been established.
