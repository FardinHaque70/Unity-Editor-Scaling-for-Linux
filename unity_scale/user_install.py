"""Per-user AppImage integration and atomic migration, without GTK or Unity.

The installed image and Editor runtime never refer to an AppImage mount. Old
source-install files remain available until an explicit verified cleanup.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import tempfile

from . import core, native_backend as backend
from .private_store import Store, atomic_json, profile, safe_root, xdg_path

APP_ID = 'io.github.unityscale.UnityScale'
MARKER = 'UNITY_EDITOR_SCALING_APPIMAGE_V2'


def _integration_paths(store):
    # Explicit Store roots are isolated installations, including desktop files.
    if store.config_dir == store.root / 'config/unity-scale':
        base = store.root / 'user-local'
        return base / 'bin/unity-scale', base / 'share/applications' / (APP_ID + '.desktop'), base / 'share/icons/hicolor/scalable/apps' / (APP_ID + '.svg')
    data = xdg_path('XDG_DATA_HOME', '.local/share')
    return Path.home() / '.local/bin/unity-scale', data / 'applications' / (APP_ID + '.desktop'), data / 'icons/hicolor/scalable/apps' / (APP_ID + '.svg')


def _legacy_settings(store):
    return store.data_dir / 'sandbox/config/unity-scale/settings.json'


def migration_document(store):
    """Merge schema-2 legacy profiles; current XDG choices win on conflict."""
    current = store.load()
    legacy = _legacy_settings(store)
    if not legacy.exists():
        return current
    safe_root(legacy)
    if legacy.stat().st_size > 1024 * 1024:
        raise core.AppError('Legacy settings exceed 1 MiB; migration left untouched')
    try:
        value = json.loads(legacy.read_text())
    except (ValueError, OSError) as exc:
        raise core.AppError('Cannot read legacy settings: ' + str(exc)) from exc
    if (not isinstance(value, dict) or value.get('schema_version') != 2
            or not isinstance(value.get('editors'), dict) or not isinstance(value.get('extra_editors', []), list)):
        raise core.AppError('Legacy settings need schema 2 with explicit override choices')
    merged = copy.deepcopy(value)
    for editor, choice in merged['editors'].items():
        if not isinstance(editor, str) or not Path(editor).is_absolute():
            raise core.AppError('Invalid legacy Editor path')
        merged['editors'][editor] = profile(choice)
    if any(not isinstance(editor, str) or not Path(editor).is_absolute() for editor in value.get('extra_editors', [])):
        raise core.AppError('Invalid extra Editor path')
    merged.update({key: item for key, item in current.items() if key not in ('editors', 'extra_editors')})
    merged['editors'].update(current['editors'])
    merged['extra_editors'] = list(dict.fromkeys(value.get('extra_editors', []) + current.get('extra_editors', [])))
    return merged


def _app_closed(store):
    """No GUI imports: detect the legacy interpreter and managed AppImage."""
    wanted = [str(store.data_dir / 'application.AppImage'), str(store.data_dir / 'launch.sh'),
              str(store.data_dir / 'unity_scale'), str(store.data_dir / 'bin/unity-scale')]
    runtime_ancestors = set()
    own_image = os.environ.get('APPIMAGE')
    if own_image:
        # Type-2 runtimes may wait for their AppRun child. That parent belongs
        # to this GUI/installer; another GUI's runtime remains a blocker.
        parent = os.getppid()
        while parent > 1:
            directory = Path('/proc') / str(parent)
            try:
                if Path(own_image).samefile(directory / 'exe'):
                    runtime_ancestors.add(parent)
                lines = (directory / 'status').read_text().splitlines()
                parent = int(next(line.split()[1] for line in lines if line.startswith('PPid:')))
            except (OSError, ValueError, StopIteration):
                break
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid() or int(process.name) in runtime_ancestors:
            continue
        try:
            cmdline = (process / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            executable = os.readlink(process / 'exe')
            environment = (process / 'environ').read_bytes().split(b'\0')
        except (OSError, ProcessLookupError):
            continue
        # The AppImage runtime may remain as an installer parent. It has no
        # settings edits and is protected by the Store lock against installers.
        if '--install-user' in cmdline:
            continue
        image_environment = ('APPIMAGE=' + wanted[0]).encode() in environment
        legacy_environment = any(item.startswith(b'PYTHONPATH=') and str(store.data_dir).encode() in item for item in environment)
        module_app = 'unity_scale' in cmdline and (image_environment or legacy_environment)
        if module_app or any(path in cmdline or path == executable for path in wanted):
            raise core.AppError('Close the scaling settings application before installing or updating')


def _editors(store, document, editors=None):
    if editors is not None:
        return [Path(getattr(editor, 'path', editor)).absolute() for editor in editors]
    found = core.discover_editors(document.get('extra_editors', []), store=store)
    paths = [Path(editor.path) for editor in found]
    # A broken owned integration must cause refusal rather than vanish in discovery.
    for editor in document['editors']:
        path = Path(editor)
        if backend.is_owned_candidate(path) and path not in paths:
            paths.append(path)
    return paths


def check_update_ready(store=None, *, editors=None):
    store = store or Store()
    _app_closed(store)
    document = migration_document(store)
    checked = []
    for public in _editors(store, document, editors):
        if backend.is_owned_candidate(public):
            original = backend.verified_original(public)
            backend._running(public)
            backend._running(original)
            checked.append(str(public))
        elif public.is_file() and backend.digest(public) == backend.SUPPORTED_ELF_SHA256:
            backend._running(public)
            checked.append(str(public))
    return {'ready': True, 'editors': checked}


def _desktop_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def _snapshot(path):
    safe_root(path)
    return (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None


def install_user(source_appimage, *, store=None, bundle=None, editors=None, check_running=True):
    """Install a managed image, merge profiles and connect supported Editors.

    Every native plan is validated before promotion. An exception restores the
    image, settings, desktop integration and all already-promoted connections.
    """
    store = store or Store()
    source = Path(source_appimage).absolute()
    if not source.is_file() or source.is_symlink():
        raise core.AppError('Run install-user from a release AppImage file')
    with source.open('rb') as stream:
        head = stream.read(11)
    if not head.startswith(b'\x7fELF') or head[8:11] not in (b'AI\x01', b'AI\x02'):
        raise core.AppError('Installation source is not an AppImage')
    backend.bundled_binaries(bundle)
    if check_running:
        _app_closed(store)
    with store.locked():
        document = migration_document(store)
        plans = []
        for public in _editors(store, document, editors):
            if backend.is_owned_candidate(public) or (public.is_file() and backend.digest(public) == backend.SUPPORTED_ELF_SHA256):
                plans.append(backend.ConnectionPlan(public, store.path, bundle=bundle))
        target = store.data_dir / 'application.AppImage'
        launcher, desktop, icon = _integration_paths(store)
        for path in (target, launcher, desktop, icon):
            safe_root(path)
        if launcher.exists() and not any(marker in launcher.read_text() for marker in
                (MARKER, 'UNITY_EDITOR_SCALING_SETTINGS_APP_V1', 'UNITY_SCALING_NATIVE_APP_LAUNCHER_V1')):
            raise core.AppError('An unrelated unity-scale command already exists')
        if desktop.exists() and 'X-UnityScale-Managed=true' not in desktop.read_text():
            raise core.AppError('An unrelated desktop entry already exists')
        originals = {path: _snapshot(path) for path in (store.path, launcher, desktop, icon)}
        journal = store.state_dir / 'install-journal.json'
        same_image = target.exists() and source.samefile(target)
        backup = None
        staged = None
        installed = []
        promoted = False
        try:
            if not same_image:
                fd, name = tempfile.mkstemp(prefix='.application-staged-', dir=store.data_dir)
                os.close(fd)
                staged = Path(name)
                shutil.copyfile(source, staged)
                staged.chmod(0o755)
                with staged.open('rb') as stream:
                    os.fsync(stream.fileno())
                if backend.digest(staged) != backend.digest(source):
                    raise core.AppError('Staged AppImage differs from source')
                if target.exists():
                    backup = store.data_dir / (staged.name + '.previous')
                    os.link(target, backup)
            atomic_json(journal, {'schema': 2, 'state': 'prepared', 'image': str(target),
                                  'image_backup': str(backup) if backup else None,
                                  'editors': [str(plan.public) for plan in plans]})
            if not same_image:
                os.replace(staged, target)
                promoted = True
                backend._sync(target.parent)
            atomic_json(store.path, document)
            for plan in plans:
                plan.apply()
                installed.append(plan)
            command = '#!/bin/sh\n# ' + MARKER + '\nexec ' + shlex.quote(str(target)) + ' "$@"\n'
            entry = '\n'.join(['[Desktop Entry]', 'Type=Application', 'Version=1.0',
                'Name=' + core.APP_NAME, 'GenericName=Unity Editor Scaling',
                'Comment=Manage Unity Editor scaling preferences', 'Exec=' + _desktop_quote(launcher),
                'TryExec=' + str(launcher), 'Icon=' + str(icon), 'Terminal=false',
                'Categories=Development;', 'Keywords=Unity;Editor;Scaling;HiDPI;Linux;',
                'StartupNotify=true', 'StartupWMClass=' + APP_ID, 'X-UnityScale-Managed=true', ''])
            backend._atomic_bytes(launcher, command.encode(), 0o755)
            backend._atomic_bytes(desktop, entry.encode(), 0o644)
            icon_source = Path(__file__).resolve().parents[1] / 'resources' / (APP_ID + '.svg')
            backend._atomic_bytes(icon, icon_source.read_bytes(), 0o644)
            result = {'schema': 2, 'state': 'installed', 'image': str(target), 'image_sha256': backend.digest(target),
                      'settings': str(store.path), 'desktop_id': APP_ID, 'connected_editors': [str(p.public) for p in plans],
                      'preferences_preserved': True, 'Unity_launched': False, 'legacy_cleanup_pending': _legacy_settings(store).exists()}
            atomic_json(journal, result)
            atomic_json(store.state_dir / 'installation.json', result)
        except BaseException as original:
            failures = []
            for plan in reversed(installed):
                try:
                    plan.rollback()
                except BaseException as exc:
                    failures.append(str(exc))
            for path, old in originals.items():
                try:
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        backend._atomic_bytes(path, *old)
                except BaseException as exc:
                    failures.append(str(exc))
            try:
                if promoted:
                    if backup is not None:
                        os.replace(backup, target)
                    else:
                        target.unlink(missing_ok=True)
            except BaseException as exc:
                failures.append(str(exc))
            atomic_json(journal, {'schema': 2, 'state': 'rollback-needs-attention' if failures else 'rolled-back',
                                  'error': str(original), 'recovery_errors': failures})
            if failures:
                raise core.AppError(str(original) + '; recovery needs attention: ' + '; '.join(failures)) from original
            raise
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        if backup is not None:
            backup.unlink(missing_ok=True)
        return result


def cleanup_legacy(store=None, *, proof):
    """Remove only unchanged legacy manifest-owned files after artifact QA.

    The caller supplies a saved runtime proof for the exact managed image.
    Unknown files and old profile copies are retained for the user to inspect.
    """
    store = store or Store()
    check_update_ready(store)
    image = store.data_dir / 'application.AppImage'
    if (not isinstance(proof, dict) or proof.get('runtime_verified') is not True
            or proof.get('image_sha256') != backend.digest(image)):
        raise core.AppError('Legacy cleanup requires runtime proof for the exact installed AppImage')
    manifest_path = store.data_dir / 'install-manifest.json'
    native_removed = {}
    document = store.load()
    owned_paths = list(dict.fromkeys(list(document['editors']) + document.get('extra_editors', [])))
    for public in _editors(store, document, owned_paths):
        if (public.parent / backend.PACKAGE_NAME / 'activation.json').is_file():
            leaves = backend.cleanup_legacy_connection(public)
            if leaves:
                native_removed[str(public)] = leaves
    if not manifest_path.is_file():
        return {'removed': [], 'native_removed': native_removed, 'retained': True}
    safe_root(manifest_path)
    if manifest_path.stat().st_size > 1024 * 1024:
        raise core.AppError('Legacy ownership manifest exceeds 1 MiB')
    manifest = json.loads(manifest_path.read_text())
    removed = []
    files = manifest.get('files', {})
    if not isinstance(files, dict):
        raise core.AppError('Invalid legacy ownership manifest')
    checked = []
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise core.AppError('Invalid legacy ownership manifest')
        name = Path(relative)
        if not name.parts or name.is_absolute() or '..' in name.parts or name.parts[0] not in ('unity_scale', 'bin', 'resources', 'native', 'launch.sh', 'README.md', 'LICENSE', 'NOTICE'):
            raise core.AppError('Invalid legacy ownership manifest')
        path = safe_root(store.data_dir / name)
        checked.append((name, path, expected))
    for name, path, expected in checked:
        if path.is_file() and backend.digest(path) == expected:
            path.unlink()
            removed.append(str(name))
    # Only empty directories are removed; never recursively delete the old tree.
    for path in sorted(store.data_dir.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not path.is_symlink() and any(path.is_relative_to(store.data_dir / leaf) for leaf in ('unity_scale', 'bin', 'resources', 'native')):
            try:
                path.rmdir()
            except OSError:
                pass
    return {'removed': removed, 'native_removed': native_removed, 'retained': True}
