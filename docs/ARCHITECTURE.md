# Architecture

The GTK application stores a profile for the canonical installed Editor path.
Hub integration redirects that Editor's launch through a small owned wrapper.
The runner starts an isolated rootless Xwayland bridge, waits for verified integer
DPI advertisement, then starts Unity with its original arguments. The runner
owns only its helper and retains it until that Editor exits. Closing the settings
app does not close the runner or Unity.

The fixed backing density B=2 and application scale multiplier M=target/desktop
produce window/input coordinate scale V=B/M. GTK font compensation is1/B.
Cursor size/theme are advertised consistently to Xlib and GTK and mapped by B,
so cursor size stays independent of the Editor's selected UI scale.

The bridge stores requested native popup allocation through integral Wayland
configure roundtrips. Its EWMH window lists let native GTK enumerate Unity
windows so docking actions work. Full source and earlier probe provenance are
included under bridge/. The bridge binary is never installed as the desktop's
system Xwayland server.

Configuration and runtime logs are outside project directories. Project arguments
are forwarded as an argv vector, without a shell. No Unity assets, packages,
scripts, preferences or licensing data are downloaded/changed by this app.
The only optional Editor-installation change is the reversible launch wrapper.

The bridge requires host xdg-output support for the fixed virtual-monitor policy.
A single primary display scale is the reference for an Editor-wide override.
Physical mixed-DPI output behavior remains unvalidated. Global absolute placement
of Wayland top-level windows is not generally available, so test unusual floating
window workflows and tools. Dynamic live scale updates are not implemented.
