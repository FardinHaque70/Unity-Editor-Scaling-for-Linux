"""Per-user AppImage integration and atomic migration, without GTK or Unity.

The installed image and Editor runtime never refer to an AppImage mount. Old
source-install files remain available until an explicit verified cleanup.
"""
from __future__ import annotations

import copy
import base64
import hashlib
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


def _saved(snapshot):
    if snapshot is None:
        return None
    data, mode = snapshot
    return dict(data=base64.b64encode(data).decode('ascii'), mode=mode,
                sha256=hashlib.sha256(data).hexdigest())


def _unsaved(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'data', 'mode', 'sha256'}:
        raise core.AppError('Invalid installation recovery snapshot')
    data = base64.b64decode(value['data'], validate=True)
    if (hashlib.sha256(data).hexdigest() != value['sha256'] or type(value['mode']) is not int
            or value['mode'] & ~0o777 or value['mode'] & 0o022):
        raise core.AppError('Installation recovery snapshot changed')
    return data, value['mode']


def _json_bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def _recover_install_locked(store):
    """Undo an interrupted promotion before using any partially updated hook.

    All old bytes and accepted new hashes are durable before the first rename.
    Validate every affected path and both original inodes before changing one.
    """
    journal = store.state_dir / 'install-journal.json'
    safe_root(journal)
    if not journal.exists():
        return False
    if journal.stat().st_uid != os.getuid() or journal.stat().st_mode & 0o077 or journal.stat().st_size > 128 * 1024 * 1024:
        raise core.AppError('Unsafe installation recovery journal')
    value = backend.parse_json(journal.read_bytes())
    if value.get('state') == 'installed' and value.get('cleanup'):
        cleanup = value['cleanup']
        target = store.data_dir / 'application.AppImage'
        if value.get('image') != str(target) or backend.digest(target) != value.get('image_sha256'):
            raise core.AppError('Committed application changed before recovery cleanup')
        for name, expected in cleanup.items():
            path = backend._safe(Path(name), owner=True)
            if path.parent != store.data_dir or not path.name.startswith('.application-staged-'):
                raise core.AppError('Invalid committed cleanup path')
            if path.exists():
                if backend.digest(path) != expected:
                    raise core.AppError('Committed recovery file changed; retained')
                path.unlink()
        backend._sync(store.data_dir)
        value.pop('cleanup')
        atomic_json(journal, value)
        return False
    if value.get('state') not in ('prepared', 'rollback-needs-attention'):
        return False
    if value.get('recovery_schema') != 1:
        raise core.AppError('Interrupted installation needs manual recovery; files retained')
    target = store.data_dir / 'application.AppImage'
    if value.get('image') != str(target):
        raise core.AppError('Installation recovery image path differs')
    launcher, desktop, icon = _integration_paths(store)
    allowed = {str(p) for p in (store.path, launcher, desktop, icon, store.state_dir / 'installation.json')}
    leaves = value.get('leaves', {})
    if set(leaves) != allowed:
        raise core.AppError('Installation recovery paths differ')
    decoded = {}
    for name, record in leaves.items():
        path = safe_root(Path(name))
        backend._safe(path, owner=True)
        old = _unsaved(record['old'])
        accepted = {record['new_sha256'], hashlib.sha256(old[0]).hexdigest() if old else None}
        if (backend.digest(path) if path.exists() else None) not in accepted:
            raise core.AppError('A file changed after interrupted installation; retained: ' + name)
        decoded[path] = old
    plans = value.get('plans', [])
    checked = []
    for record in plans:
        public, backup, package = backend.paths(record['public'])
        if public.name != 'Unity' or not public.is_absolute():
            raise core.AppError('Invalid recovery Editor path')
        for path in (public, backup, package):
            backend._safe(path, owner=True)
        original = backup if backup.exists() else public
        if (record['existing'] and not backup.exists()) or backend._identity(original) != record['original_identity'] or backend.digest(original) != backend.SUPPORTED_ELF_SHA256:
            raise core.AppError('Original Editor changed during interrupted installation; retained')
        backend._running(public)
        backend._running(original)
        old_public = _unsaved(record['old_public'])
        accepted = {record['new_public_sha256'], hashlib.sha256(old_public[0]).hexdigest() if old_public else backend.SUPPORTED_ELF_SHA256}
        if backend.digest(public) not in accepted:
            raise core.AppError('Editor launcher changed during interrupted installation; retained')
        files = record['files']
        if set(files) != {'activation.json', 'wrapper-v2', 'native-v2.so'}:
            raise core.AppError('Invalid recovery native package paths')
        old_files = {}
        for name, item in files.items():
            path = backend._safe(package / name, owner=True)
            old = _unsaved(item['old'])
            accepted = {item['new_sha256'], hashlib.sha256(old[0]).hexdigest() if old else None}
            if (backend.digest(path) if path.exists() else None) not in accepted:
                raise core.AppError('Native package changed during interrupted installation; retained')
            old_files[path] = old
        checked.append((record, public, backup, package, old_public, old_files))
    image_old = value.get('image_old_sha256')
    image_promoted = value.get('image_promoted')
    if type(image_promoted) is not bool:
        raise core.AppError('Installation recovery image operation is invalid')
    image_current = backend.digest(target) if target.exists() else None
    accepted_images = {image_old, value['image_new_sha256']}
    # An outer signed updater can already have restored its old AppImage.
    # A same-image native installer never owned that executable swap. Accept
    # only the exact old receipt hash, not an arbitrary replacement image.
    if not image_promoted:
        old_receipt = decoded.get(store.state_dir / 'installation.json')
        if old_receipt is not None:
            previous = backend.parse_json(old_receipt[0])
            if previous.get('image') == str(target):
                accepted_images.add(previous.get('image_sha256'))
    if image_current not in accepted_images:
        raise core.AppError('Application changed during interrupted installation; retained')
    backend._safe(target, owner=True)
    image_backup = Path(value['image_backup']) if value.get('image_backup') else None
    if image_backup is not None:
        backend._safe(image_backup, owner=True)
        if (image_backup.parent != store.data_dir or not image_backup.name.startswith('.application-staged-')
                or not image_backup.name.endswith('.previous')
                or (backend.digest(image_backup) if image_backup.exists() else image_current) != image_old):
            raise core.AppError('Application recovery backup changed')
    staged = value.get('staged')
    if staged:
        staged = safe_root(Path(staged))
        if (staged.parent != store.data_dir or not staged.name.startswith('.application-staged-')
                or (staged.exists() and backend.digest(staged) != value['image_new_sha256'])):
            raise core.AppError('Staged recovery image changed; retained')
    # Every validation succeeded. Roll back in reverse promotion order.
    for record, public, backup, package, old_public, old_files in reversed(checked):
        if old_public is not None:
            backend._atomic_bytes(public, *old_public)
        elif backup.exists():
            if public.samefile(backup):
                backup.unlink()
            else:
                os.replace(backup, public)
            backend._sync(public.parent)
        for path, old in old_files.items():
            if old is None:
                path.unlink(missing_ok=True)
            else:
                backend._atomic_bytes(path, *old)
        if package.exists():
            if not any(package.iterdir()):
                package.rmdir()
            elif record['old_package_mode'] is not None:
                package.chmod(record['old_package_mode'])
    for path, old in decoded.items():
        if old is None:
            path.unlink(missing_ok=True)
        else:
            backend._atomic_bytes(path, *old)
    if image_backup is not None and image_backup.exists():
        os.replace(image_backup, target)
    elif image_promoted and image_old is None:
        target.unlink(missing_ok=True)
    backend._sync(store.data_dir)
    if staged:
        staged.unlink(missing_ok=True)
    atomic_json(journal, {'schema': 2, 'state': 'rolled-back', 'recovered_after_interruption': True})
    return True


def recover_install(store=None):
    store = store or Store()
    with store.locked():
        return _recover_install_locked(store)


def uninstall_user(store=None, *, editors=None):
    """Restore verified closed Editors before removing owned app integration."""
    store = store or Store()
    _app_closed(store)
    with store.locked():
        _recover_install_locked(store)
        target = store.data_dir / 'application.AppImage'
        receipt_path = store.state_dir / 'installation.json'
        safe_root(receipt_path)
        receipt = backend.parse_json(receipt_path.read_bytes())
        if receipt.get('image') != str(target) or receipt.get('image_sha256') != backend.digest(target):
            raise core.AppError('Managed application changed; uninstall left files untouched')
        launcher, desktop, icon = _integration_paths(store)
        for path in (target, launcher, desktop, icon):
            backend._safe(path, owner=True)
        if MARKER not in launcher.read_text() or str(target) not in launcher.read_text() or 'X-UnityScale-Managed=true' not in desktop.read_text():
            raise core.AppError('Application integration changed; uninstall left files untouched')
        connected = []
        for public in _editors(store, store.load(), editors):
            if backend.is_owned_candidate(public):
                original = backend.verified_original(public)
                backend._running(public)
                backend._running(original)
                connected.append(public)
        restored = []
        for public in connected:
            if backend._receipt(public).get('schema') == 2:
                backend.cleanup_legacy_connection(public)
            restored.append(backend.restore(public))
        removed = []
        for path in (launcher, desktop, icon, target, receipt_path, store.state_dir / 'install-journal.json'):
            path.unlink(missing_ok=True)
            removed.append(str(path))
        return dict(uninstalled=True, restored_editors=restored, removed=removed, preferences_retained=str(store.path))


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
        _recover_install_locked(store)
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
        originals = {path: _snapshot(path) for path in (store.path, launcher, desktop, icon, store.state_dir / 'installation.json')}
        journal = store.state_dir / 'install-journal.json'
        same_image = target.exists() and source.samefile(target)
        backup = None
        staged = None
        installed = []
        promoted = False
        command = '#!/bin/sh\n# ' + MARKER + '\nexec ' + shlex.quote(str(target)) + ' "$@"\n'
        entry = '\n'.join(['[Desktop Entry]', 'Type=Application', 'Version=1.0',
            'Name=' + core.APP_NAME, 'GenericName=Unity Editor Scaling',
            'Comment=Manage Unity Editor scaling preferences', 'Exec=' + _desktop_quote(launcher),
            'TryExec=' + str(launcher), 'Icon=' + str(icon), 'Terminal=false',
            'Categories=Development;', 'Keywords=Unity;Editor;Scaling;HiDPI;Linux;',
            'StartupNotify=true', 'StartupWMClass=' + APP_ID, 'X-UnityScale-Managed=true', ''])
        icon_source = Path(__file__).resolve().parents[1] / 'resources' / (APP_ID + '.svg')
        result = {'schema': 2, 'version': core.VERSION, 'state': 'installed', 'image': str(target), 'image_sha256': backend.digest(source),
                  'settings': str(store.path), 'desktop_id': APP_ID, 'connected_editors': [str(p.public) for p in plans],
                  'preferences_preserved': True, 'Unity_launched': False, 'legacy_cleanup_pending': _legacy_settings(store).exists()}
        replacements = {store.path: _json_bytes(document), launcher: command.encode(), desktop: entry.encode(),
                        icon: icon_source.read_bytes(), store.state_dir / 'installation.json': _json_bytes(result)}
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
            recovery = {'schema': 2, 'recovery_schema': 1, 'state': 'prepared', 'image': str(target),
                        'image_promoted': not same_image,
                        'image_backup': str(backup) if backup else None, 'staged': str(staged) if staged else None,
                        'image_old_sha256': backend.digest(target) if target.exists() else None,
                        'image_new_sha256': result['image_sha256'],
                        'leaves': {str(path): dict(old=_saved(old), new_sha256=hashlib.sha256(replacements[path]).hexdigest())
                                   for path, old in originals.items()},
                        'plans': [dict(public=str(plan.public), existing=plan.existing, original_identity=plan.original_identity,
                                       old_public=_saved((plan.old_public, plan.original_mode)) if plan.existing else None,
                                       new_public_sha256=plan.activation['wrapper_sha256'], old_package_mode=plan.old_package_mode,
                                       files={name: dict(old=_saved(old), new_sha256=hashlib.sha256(
                                           _json_bytes(plan.activation) if name == 'activation.json' else plan.content[name]).hexdigest())
                                              for name, old in plan.old_files.items()}) for plan in plans]}
            atomic_json(journal, recovery)
            if not same_image:
                os.replace(staged, target)
                promoted = True
                backend._sync(target.parent)
            atomic_json(store.path, document)
            for plan in plans:
                plan.apply()
                installed.append(plan)
            backend._atomic_bytes(launcher, command.encode(), 0o755)
            backend._atomic_bytes(desktop, entry.encode(), 0o644)
            backend._atomic_bytes(icon, icon_source.read_bytes(), 0o644)
            atomic_json(store.state_dir / 'installation.json', result)
            cleanup = {str(path): backend.digest(path) for path in (backup, staged) if path is not None and path.exists()}
            atomic_json(journal, dict(result, cleanup=cleanup))
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
            failure_record = dict(recovery, state='rollback-needs-attention', error=str(original), recovery_errors=failures) if failures else {
                'schema': 2, 'state': 'rolled-back', 'error': str(original), 'recovery_errors': []}
            atomic_json(journal, failure_record)
            if failures:
                raise core.AppError(str(original) + '; recovery needs attention: ' + '; '.join(failures)) from original
            if backup is not None:
                backup.unlink(missing_ok=True)
            raise
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        if backup is not None:
            backup.unlink(missing_ok=True)
        atomic_json(journal, result)
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
