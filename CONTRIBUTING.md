# Contributing

This beta targets KDE Wayland. Reports from other GPUs, Unity versions and mixed-DPI
setups are welcome; distinguish tested behavior from proposed compatibility.

## Development

Install the runtime and build dependencies in [INSTALL.md](docs/INSTALL.md), then:

```sh
./packaging/build-bridge.sh
UNITY_SCALE_TEST_GUI=1 GSETTINGS_BACKEND=memory python3 -m unittest discover -s tests -v
./bin/unity-scale --smoke-test
./bin/unity-scale
```

The GUI tests require a graphical session. On a headless builder use Xvfb with
`GDK_BACKEND=x11`; the supplied GitHub Actions workflow demonstrates this setup.
Editor integration tests use disposable executable fixtures and do not wrap your
installed Unity Editor.

The Python application is in `unity_scale/`. Its native bridge source is in
`bridge/unity-scaling-xwayland-satellite-v5.2/`. Preserve the distinction between
integer render density, application window/input mapping and cursor mapping.
See [ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing these transforms.

## Changes and reports

Keep changes focused and include verification appropriate to the behavior changed.
Use an isolated project for interactive Editor testing. Never force-close an
Editor with unsaved work or overwrite files after an integration ownership conflict.

A useful bug report includes the app/Unity version, desktop/compositor, GPU/driver,
desktop scale, chosen Editor scale, reproduction steps and expected behavior.
The app's Diagnostics view omits private project paths and raw logs. Review raw
Editor logs before sharing them; they may contain account or licensing information.

Keep existing license and attribution notices. General bridge improvements should
be split into focused upstream contributions; consult the upstream project's current
contribution and AI policies before submitting there. AI-assisted changes should be
reviewed and tested and described honestly.
