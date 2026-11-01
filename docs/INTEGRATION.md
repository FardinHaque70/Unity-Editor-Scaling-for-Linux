# Editor-wide launch integration

Unity Editor UI Scalar for Linux applies settings to an installed Editor.
A profile is shared by all projects opened with that Editor version. No project
scripts, packages or settings are installed.

## What Override scale changes

The app first records the original executable's hash and permissions, then makes
a hard-link backup named `Unity.unity-scale-original` in the same Editor directory.
It atomically replaces `Unity` with a small owned Python launcher. The original
compiled executable bytes are preserved, not patched. Two small integration
records track ownership (one beside the executable, one in the user state folder).

Unity Hub continues launching its existing Editor path. The wrapper forwards its
arguments through the scaling runner. License/version/headless invocations bypass
scaling. If the application entry point disappears, the wrapper can fall back to
the preserved original. It does not retry Unity after a runner failure, avoiding
duplicate Editors. Closing the app does not terminate a running Editor.

**This does not create a separate scaled-Unity shortcut.** The installer creates
only a **Unity Editor UI Scalar for Linux** settings-app menu entry. The original
Editor launch path is
wrapped while enabled; disabling restores the original file. The interface must
not describe this as leaving the original launch path unchanged.

## Disable, updates and removal

Turning off Override scale restores the original executable only after checking ownership, hash and
permissions. Original inode/bytes/mode are retained. Changes from an updater or
another program are treated as conflicts; neither file is overwritten blindly.

**Turn off Override scale before updating or uninstalling that Editor in Unity Hub.**
After an Editor update finishes, scan again and enable the new installation.
The app never modifies Hub's databases, download configuration or modules.
System-owned Editor installations must be managed by their administrator; the
app does not run sudo or make such an installation writable.

Uninstalling the app first restores its enabled Editor integrations. A
conflict stops the uninstall so the app and backups remain available for repair.
Configuration and logs are retained. If an original backup was changed or lost,
recover the Editor from your official installation rather than forcing a restore.

## Native application identity

While integration is enabled, Unity's `EditorApplication.applicationPath` reports
the preserved executable's backup filename. Resource loading, project import,
compilation and graphical startup were tested successfully with Unity6000.3.27f2.
Plugins that require the executable to be named exactly `Unity` need beta testing.
The runner must retain the private display during Unity's own project relaunch;
that behavior is covered by the standalone relaunch test in VALIDATION.md.

Existing prototype audit launchers carry an explicit scaled-session marker and
bypass the wrapper, so they retain their own independent helper lifetime.
