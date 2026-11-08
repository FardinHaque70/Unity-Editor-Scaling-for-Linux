# Installation and restoration

## Requirements

Requirements: system Python 3.10+ with PyGObject, GTK 4.10+, and libadwaita 1.4+ for the settings app; C/C++ compilers, `pkg-config`, and GTK 3, json-c, and OpenSSL development files to build the native components. An existing supported Unity installation must be writable by your user. Its path must contain no whitespace or colon. Dependencies are provided by your distribution; the installer does not download them.

The native backend targets the exact **Unity 6000.3.27f2 Linux x86_64** executable on **KDE Wayland**, using **GTK 3 over X11/Xwayland and OpenGL**. The launcher does not select a renderer; local trials explicitly used `-force-glcore`. The executable must match this SHA-256:

```text
d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec
```

## Install and use

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
