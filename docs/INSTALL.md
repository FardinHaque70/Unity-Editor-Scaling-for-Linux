# Installation and command line

Unity Editor UI Scalar for Linux is a user-local KDE Wayland beta for x86_64
Linux. It needs Python 3.10+, GTK 4.10+, libadwaita 1.4+, Xwayland 23.1+, and a compositor supporting
xdg-shell, viewporter and xdg-output. Native X11 sessions are outside this beta's
scope. Other desktops and mixed-DPI hardware need further testing.

## System dependencies

Install dependencies through your distribution package manager:

```sh
# Arch / CachyOS
sudo pacman -S python python-gobject gtk4 libadwaita xorg-xwayland libxcb xcb-util-cursor kscreen wayland-utils

# Ubuntu 24.04 / KDE neon
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 xwayland libxcb-cursor0 libx11-6 kscreen wayland-utils

# Fedora KDE
sudo dnf install python3 python3-gobject gtk4 libadwaita xorg-x11-server-Xwayland xcb-util-cursor libX11 kscreen wayland-utils
```

The installer checks the GTK versions and native bridge libraries. Older versions
of these distributions may not provide the required GTK or libadwaita release.

**The current locally built native helper requires glibc 2.43.** Build locally
on older distributions. The prepared release workflow targets an older ABI;
its configuration is not evidence of a successful external CI run. Check the
[release and validation notes](VALIDATION.md) for the artifact you use.

## Build the bridge locally

Install stable Rust, a C linker, clang, pkg-config, libxcb and xcb-util-cursor
headers. For Ubuntu, the native build packages are:

```sh
sudo apt install build-essential clang pkg-config libxcb1-dev libxcb-cursor-dev
```

From the repository root:

```sh
./packaging/build-bridge.sh
./install.sh
```

The build script uses locked Rust dependencies and runs the bridge regression
suite. Complete modified source is in
`bridge/unity-scaling-xwayland-satellite-v5.2`. A compatible prebuilt release
does not require a Rust toolchain.

## Install

From an extracted release with a compatible helper, run:

```sh
./install.sh
```

No sudo or pip is needed for the application installation. The default prefix
is `~/.local`. Open **Unity Editor UI Scalar for Linux** from your application
menu, or run
`~/.local/bin/unity-scale`. Distribution GTK libraries are used; an AppImage is
not supplied.

The installer stages all payloads before replacing an existing installation and
checks ownership before an upgrade. See [release packaging](RELEASING.md) for
custom-prefix and release workflows.

## Command line

```sh
unity-scale editors
unity-scale configure --editor /path/to/Editor/Unity --scale 150
unity-scale enable --editor /path/to/Editor/Unity
unity-scale run --editor /path/to/Editor/Unity --project '/path/to/game'
unity-scale run --editor /path/to/Editor/Unity --dry-run -- -projectPath '/path/to/game'
unity-scale diagnostics
unity-scale disable --editor /path/to/Editor/Unity
```

Profiles use the installed Editor path as their identity. GUI and command-line
settings are shared. A dry run reports the launch plan without starting Unity.
See [Editor integration](INTEGRATION.md) before updating or moving an Editor.

Configuration is stored in `$XDG_CONFIG_HOME/unity-scale`, defaulting to
`~/.config/unity-scale`. Logs and integration state use
`$XDG_STATE_HOME/unity-scale`, defaulting to `~/.local/state/unity-scale`.
Diagnostics omit project paths and raw Editor logs. Raw runtime logs may contain
private information; they are not uploaded automatically.

## Uninstall

For the default installation:

```sh
~/.local/share/unity-scale/application/uninstall.sh
```

Uninstall restores this installation's enabled Editor wrappers before removing
the app. An ownership conflict or changed original backup stops removal rather
than overwriting a changed executable. Configuration and logs are retained for
troubleshooting. See [restoration details](INTEGRATION.md#disable-updates-and-removal).
