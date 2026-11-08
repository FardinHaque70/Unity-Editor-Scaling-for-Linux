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
    parser = argparse.ArgumentParser(description='Install the release AppImage for this user without launching Unity')
    parser.add_argument('--appimage', type=Path, help='Release AppImage (defaults to APPIMAGE when running an AppImage)')
    parser.add_argument('--check', action='store_true', help='Validate native binaries and closed Editor state only')
    parser.add_argument('--restore-editor', type=Path)
    parser.add_argument('--cleanup-legacy-proof', type=Path, help='Artifact runtime QA JSON authorizing manifest-owned cleanup')
    args = parser.parse_args()
    from unity_scale import native_backend
    from unity_scale.user_install import install_user, check_update_ready, cleanup_legacy
    if args.restore_editor is not None:
        if args.check:
            raise RuntimeError('--restore-editor cannot be combined with --check')
        result = native_backend.restore(args.restore_editor)
    elif args.cleanup_legacy_proof is not None:
        result = cleanup_legacy(proof=json.loads(args.cleanup_legacy_proof.read_text()))
    elif args.check:
        native_backend.bundled_binaries()
        result = check_update_ready()
    else:
        source = args.appimage or os.environ.get('APPIMAGE')
        if not source:
            raise RuntimeError('Supply --appimage /path/to/release.AppImage; source installations are no longer copied into user data')
        result = install_user(Path(source))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))
