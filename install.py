#!/usr/bin/python3
"""Reversible prerelease app and verified per-Editor startup launcher setup."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tarfile
import tempfile

SOURCE = Path(__file__).resolve().parent
DESTINATION = Path.home() / '.local/share/unity-editor-scaling-for-linux'
LAUNCHER = Path.home() / '.local/bin/unity-scale'
DESKTOP = Path.home() / '.local/share/applications/io.github.unityscale.UnityScale.desktop'
ICON = Path.home() / '.local/share/icons/hicolor/scalable/apps/io.github.unityscale.UnityScale.svg'
APP_ID = 'io.github.unityscale.UnityScale'
APP_NAME = 'Unity Editor Scaling for Linux'


def check_path(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RuntimeError('Refusing a symlink installation path: ' + str(part))


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.unity-scale-update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def quote_desktop(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def rollback_update(connections, promoted, moved_old, previous, old_files, restore_native):
    """Attempt every independent recovery even when one Editor cannot restore."""
    errors = []
    for public in reversed(connections):
        try:
            restore_native(public)
        except BaseException as exc:
            errors.append('Editor ' + str(public) + ': ' + str(exc))
    try:
        if promoted:
            shutil.rmtree(DESTINATION)
        if moved_old:
            os.replace(previous, DESTINATION)
    except BaseException as exc:
        errors.append('Application: ' + str(exc))
    for path, data in old_files.items():
        try:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, *data)
        except BaseException as exc:
            errors.append(str(path) + ': ' + str(exc))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate sources and paths without installing')
    parser.add_argument('--restore-editor', type=Path, help='Restore this app-owned Editor launcher to its exact preserved original')
    args = parser.parse_args()
    from unity_scale import core
    from unity_scale import native_backend
    if args.restore_editor is not None:
        if args.check:
            raise RuntimeError('--restore-editor cannot be combined with --check')
        print(json.dumps(native_backend.restore(args.restore_editor), indent=2))
        return
    required = ['unity_scale/gui.py', 'unity_scale/core.py', 'unity_scale/private_store.py',
                'unity_scale/native_backend.py', 'unity_scale/native_launch.py', 'unity_scale/gui_state.py', 'unity_scale/__main__.py',
                'native/launcher.c', 'native/product_policy.c', 'native/product_policy.h', 'native/host_environment.h',
                'native/product/source-manifest.json',
                'bin/unity-scale', 'launch.sh', 'resources/' + APP_ID + '.svg', 'README.md', 'LICENSE', 'NOTICE']
    for relative in required:
        if not (SOURCE / relative).is_file():
            raise RuntimeError('Missing app file: ' + relative)
    for path in (DESTINATION, LAUNCHER, DESKTOP, ICON):
        check_path(path)
    if LAUNCHER.exists() and not any(marker in LAUNCHER.read_text() for marker in
            ('UNITY_EDITOR_SCALING_SETTINGS_APP_V1', 'UNITY_SCALING_NATIVE_APP_LAUNCHER_V1')):
        raise RuntimeError('An unrelated unity-scale command already exists; left untouched.')
    if DESKTOP.exists() and 'X-UnityScale-Managed=true' not in DESKTOP.read_text():
        raise RuntimeError('An unrelated menu entry already exists; left untouched.')
    native_backend.bundled_source()
    if args.check:
        print('Application and frozen native sources verified; no files installed or Editor launched.')
        return
    # Complete source/dependency checks before changing the installed app.
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def owner(name):
        return bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                            'org.freedesktop.DBus', 'NameHasOwner', GLib.Variant('(s)', (name,)),
                            GLib.VariantType.new('(b)'), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    running = [name for name in (APP_ID, APP_ID + '.Private') if owner(name)]
    if running:
        raise RuntimeError('Close the scaling settings app before updating. Pending edits must finish first.')
    # Stage every native connection before changing either app or Editor files.
    # Installation is the one-time setup; ordinary GUI toggles only save choices.
    native_temporary = tempfile.TemporaryDirectory(prefix='unity-native-app-install-')
    native_plans = []
    connected_now = []
    already_connected = []
    settings_path = DESTINATION / 'sandbox/config/unity-scale/settings.json'
    extra = []
    if settings_path.is_file():
        existing = json.loads(settings_path.read_text())
        extra = existing.get('extra_editors', [])
    try:
        for editor in core.discover_editors(extra):
            if native_backend.is_owned_candidate(editor.path):
                native_backend.verified_original(editor.path)
                already_connected.append(editor.path)
                continue
            if editor.version != '6000.3.27f2' or native_backend.digest(editor.path) != native_backend.SUPPORTED_ELF_SHA256:
                continue
            native_backend._running(Path(editor.path))
            prepared = Path(native_temporary.name) / ('editor-' + str(len(native_plans)))
            native_backend.prepare_supported(editor.path, settings_path, prepared)
            native_plans.append((editor.path, prepared, native_backend.digest(prepared / 'receipt.json')))
    except BaseException:
        native_temporary.cleanup()
        raise
    archive = SOURCE.parent / 'Archive'
    archive.mkdir(exist_ok=True)
    backup = archive / 'app-before-focused-2026-11-04.tar.gz'
    if backup.exists():
        backup = archive / ('app-before-focused-' + secrets.token_hex(4) + '.tar.gz')
    with tarfile.open(backup, 'w:gz') as tar:
        if DESTINATION.exists():
            tar.add(DESTINATION, arcname='application')
        for path in (LAUNCHER, DESKTOP, ICON):
            if path.exists():
                tar.add(path, arcname='user-local/' + path.name)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.unity-scaling-update-', dir=DESTINATION.parent))
    previous = stage.with_name(stage.name + '-previous')
    old_files = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None
                 for p in (LAUNCHER, DESKTOP, ICON)}
    promoted = False
    moved_old = False
    try:
        for name in ('unity_scale', 'bin', 'resources', 'native'):
            shutil.copytree(SOURCE / name, stage / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('launch.sh', 'README.md', 'LICENSE', 'NOTICE'):
            shutil.copy2(SOURCE / name, stage / name)
        old_data = DESTINATION / 'sandbox'
        if old_data.exists():
            if any(p.is_symlink() for p in [old_data, *old_data.rglob('*')]):
                raise RuntimeError('App data contains a symlink; preferences left untouched.')
            shutil.copytree(old_data, stage / 'sandbox')
        hashes = {}
        for p in stage.rglob('*'):
            if p.is_file() and not p.is_relative_to(stage / 'sandbox'):
                hashes[str(p.relative_to(stage))] = hashlib.sha256(p.read_bytes()).hexdigest()
        (stage / 'install-manifest.json').write_text(json.dumps(dict(application=APP_NAME, version=core.VERSION, prerelease=True,
            native_backend_available=bool(native_plans or already_connected), native_scope='Unity6000.3.27f2/KDEWayland/OpenGL/startup-only', files=hashes), indent=2) + '\n')
        if DESTINATION.exists():
            os.replace(DESTINATION, previous)
            moved_old = True
        os.replace(stage, DESTINATION)
        promoted = True
        command = '#!/usr/bin/python3\n# UNITY_EDITOR_SCALING_SETTINGS_APP_V1\nimport os,sys\nentry=' + repr(str(DESTINATION / 'launch.sh')) + '\nos.execv(entry,[entry,*sys.argv[1:]])\n'
        desktop = '\n'.join(['[Desktop Entry]', 'Type=Application', 'Version=1.0', 'Name=' + APP_NAME,
            'GenericName=Unity Editor Scaling', 'Comment=Manage project-independent Unity Editor scaling preferences',
            'Exec=' + quote_desktop(LAUNCHER), 'TryExec=' + str(LAUNCHER), 'Icon=' + str(ICON), 'Terminal=false',
            'Categories=Development;', 'Keywords=Unity;Editor;Scaling;HiDPI;Linux;', 'StartupNotify=true',
            'StartupWMClass=' + APP_ID, 'X-UnityScale-Managed=true', 'X-UnityScale-Frontend=Settings', ''])
        atomic_write(LAUNCHER, command.encode(), 0o755)
        atomic_write(DESKTOP, desktop.encode(), 0o644)
        atomic_write(ICON, (SOURCE / ('resources/' + APP_ID + '.svg')).read_bytes(), 0o644)
        if shutil.which('desktop-file-validate'):
            subprocess.run(['desktop-file-validate', str(DESKTOP)], check=True)
        for public, prepared, pin in native_plans:
            native_backend.install(prepared, pin)
            connected_now.append(public)
    except BaseException as original:
        failures = rollback_update(connected_now, promoted, moved_old, previous, old_files, native_backend.restore)
        if failures:
            raise RuntimeError('Update failed: ' + str(original) + '; recovery needs attention: ' + '; '.join(failures)) from original
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        native_temporary.cleanup()
    if previous.exists():
        shutil.rmtree(previous)
    receipt = dict(application=APP_NAME, version=core.VERSION, prerelease=True, installed=str(DESTINATION),
                   backup=str(backup), preferences_preserved=True, desktop_id=DESKTOP.name,
                   native_backend_available=bool(connected_now or already_connected), connected_editors=already_connected + connected_now,
                   original_elf_bytes_preserved=True, Unity_launched=False, desktop_scale_modified=False,
                   requires_unity_restart=True, production_applied=False, presented=False)
    (SOURCE.parent / 'APP-INSTALL-RESULT.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))
