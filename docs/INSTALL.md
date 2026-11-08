# AppImage installation and restoration

## Compatibility

The release AppImage targets Linux x86_64 with an Ubuntu 22.04 glibc baseline. Python, PyGObject, GTK 4 and libadwaita are bundled; compilers, Python packages and development headers are not required on the user's computer. Your operating system still supplies its base C runtime, display server, graphics drivers and the runtime dependencies required by Unity itself.

Native scaling supports the exact **Unity 6000.3.27f2 Linux x86_64** executable on **KDE Plasma Wayland**, with Unity using **GTK 3 over X11/Xwayland and OpenGL**. Local trials explicitly used `-force-glcore`; the scaling launcher does not select a graphics renderer. The original executable must match:

```text
d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec
```

The installation must be owned and writable by your user. Editor paths containing whitespace or a colon are refused because of native preload path constraints. The AppImage's own location may contain spaces. Root-owned installations, other Unity builds, other desktop sessions and renderers are unsupported. Do not run this app with `sudo`.

## First launch

Save your work and close Unity and any older instance of the scaling app. Download the release AppImage, then run:

```sh
chmod +x Unity-Editor-Scaling-for-Linux-x86_64.AppImage
./Unity-Editor-Scaling-for-Linux-x86_64.AppImage
```

Opening the downloaded image installs a managed copy for the current user, preserves existing schema-2 preferences, and connects discovered compatible Editors. It retains the established application-menu identity and `unity-scale` command. It does not launch or close Unity for you. Unsupported installations can be listed but cannot receive native scaling.

If mounting the image is unavailable, use:

```sh
./Unity-Editor-Scaling-for-Linux-x86_64.AppImage --appimage-extract-and-run
```

The pinned Type-2 runtime does not require a host `libfuse2` package. Normal mounted execution still depends on the host permitting FUSE; extract-and-run avoids that requirement. You can also request installation without opening a settings window:

```sh
./Unity-Editor-Scaling-for-Linux-x86_64.AppImage --appimage-extract-and-run --install-user
```

After successful installation, use the application-menu entry or `unity-scale`. The downloaded file is no longer the managed copy and can be removed. Keep one managed image; do not manually delete native backups or activation files.

## Scale settings

Select your Editor, turn on **Custom scale**, and choose a whole percentage from **100% to 200%**. Valid changes save automatically. Wait for **Saved**, then restart Unity through its normal launcher. Every project using that Editor receives its saved setting. The settings app can be closed.

Turning Custom scale off selects Unity default on the next launch. It does not restore the original executable or remove the connection. Explicit Custom 100% still uses the custom native paths and GTK DPI policy. The custom percentage is remembered while the toggle is off.

Saved settings and connection status are separate from the effective scale of an already running Editor. The app does not rescale an active Unity process or certify a rendered frame.

The command-line equivalents are:

```sh
unity-scale configure --editor /absolute/path/to/Editor/Unity --scale 150
unity-scale configure --editor /absolute/path/to/Editor/Unity --unity-default
unity-scale status --editor /absolute/path/to/Editor/Unity
```

## Managed files

With default XDG locations, the app keeps:

| Location | Purpose |
| --- | --- |
| `~/.local/share/unity-editor-scaling-for-linux/application.AppImage` | One managed application image |
| `~/.config/unity-editor-scaling-for-linux/settings.json` | Schema-2 preferences, keyed by Editor path |
| `~/.local/state/unity-editor-scaling-for-linux/` | Installation receipt and transaction/recovery state |
| `~/.local/bin/unity-scale` | Command opening the managed image |
| `~/.local/share/applications/io.github.unityscale.UnityScale.desktop` | Application-menu entry and existing favorite identity |
| `~/.local/share/icons/hicolor/scalable/apps/io.github.unityscale.UnityScale.svg` | Application icon |
| `Editor/.Unity.unity-scale-original` | Original Unity executable, required for restoration |
| `Editor/.unity-editor-scaling/` | Prebuilt runtime, launcher copy and schema-2 activation record |

Absolute `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_STATE_HOME` overrides are respected. Native components live beside the Editor, not inside an AppImage mount. They continue working after the GUI exits or the downloaded AppImage moves.

## Updates

Choose **⋮ → Check for Updates**. The app reads GitHub's release list only when requested; it adds no background updater, service or telemetry. A prerelease accepts newer prereleases and stable releases. A stable build accepts only stable releases.

The update dialog shows the version, notes and download progress, with cancellation. Before execution, the updater verifies an Ed25519-signed manifest binding the version, channel, architecture, filename, size and SHA-256. A helper outside the mounted image replaces the managed image atomically, restarts it and waits for a health acknowledgement. One temporary rollback copy is retained until verification succeeds. Failure restores the previous image; interrupted transactions retain recovery information.

Affected Editors must be closed before updating their native components. The app does not close a running user Editor automatically. Keep recovery state if an update reports a failure, rather than deleting files to bypass the check.

## Restore an Editor

Restore before upgrading or removing a connected Editor and before uninstalling the scaling app. Save your work and close that Editor, then run:

```sh
unity-scale restore --editor /absolute/path/to/Editor/Unity
```

Restoration verifies ownership, activation data and the original backup before putting the original executable back. It refuses unrelated modifications instead of overwriting them. Keep the backup and activation record until restoration succeeds. If restoration reports a refusal, retain those files and include the error in an issue.

After restoring all connected Editors, the managed image, command, desktop entry, icon, settings and app state listed above can be removed. Keep preferences if you intend to reinstall. A restored Editor no longer depends on those application files.

## Source and development

The release includes the source revision and pinned build inputs. Building the AppImage is an ephemeral CI/developer task; it is not part of normal installation. See [architecture](ARCHITECTURE.md), [validation](VALIDATION.md) and [third-party sources](THIRD_PARTY.md).
