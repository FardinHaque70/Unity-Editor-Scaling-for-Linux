"""Reversible, explicitly invoked native startup delivery. Never launches Unity.

Preparing writes only its requested staging directory. Installing/restoring are
separate operations; the GUI only saves preferences and reports verified state.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile

from .native_launch import SUPPORTED_ELF_SHA256, LaunchError, digest, parse_json
from .private_store import atomic_json

MARKER = b'UNITY_EDITOR_SCALING_NATIVE_LAUNCHER_V1'
PACKAGE_NAME = '.unity-editor-scaling'
BACKUP_NAME = '.Unity.unity-scale-original'
NATIVE_SOURCE = Path(__file__).resolve().parents[1] / 'native'


def paths(public):
    public = Path(public).expanduser().absolute()
    return public, public.parent / BACKUP_NAME, public.parent / PACKAGE_NAME


def _safe(path, *, owner=False):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise LaunchError('Refusing a symlink integration path: ' + str(part))
    if path.exists() and owner and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o022):
        raise LaunchError('Integration files must be owned by this user and not group/world writable')
    return path


def _identity(path):
    s = path.stat()
    return {key: getattr(s, key) for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')}


def _sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _running(public):
    wanted = public.stat()
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():
            continue
        try:
            item = (process / 'exe').stat()
            if (item.st_dev, item.st_ino) == (wanted.st_dev, wanted.st_ino):
                raise LaunchError('Close this Editor before changing its launcher; no live process will be modified')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue


def is_owned_candidate(public):
    public, _, package = paths(public)
    if package.exists():
        return True
    try:
        with public.open('rb') as stream:
            return MARKER in stream.read(1024 * 1024)
    except OSError:
        return False


def _receipt(public):
    public, backup, package = paths(public)
    _safe(public, owner=True)
    _safe(backup, owner=True)
    _safe(package, owner=True)
    file = _safe(package / 'receipt.json', owner=True)
    if not file.is_file() or file.stat().st_size > 65536:
        raise LaunchError('Owned native integration receipt is missing or oversized')
    value = parse_json(file.read_bytes())
    if (not isinstance(value, dict) or value.get('schema') != 1 or value.get('owner_uid') != os.getuid()
            or value.get('marker') != MARKER.decode() or value.get('public_editor') != str(public)
            or value.get('target_exe') != str(backup) or value.get('original_sha256') != SUPPORTED_ELF_SHA256
            or value.get('constructor_contract') != 'product-profile-v1'
            or value.get('host_environment_abi') != 1 or value.get('restore_host_on_refusal') is not True):
        raise LaunchError('Native integration receipt does not match this Editor')
    for name in ('native.so', 'wrapper'):
        _safe(package / name, owner=True)
        if digest(package / name) != value['files'][name]:
            raise LaunchError('Owned native package changed: ' + name)
    return value


def verified_original(public, *, full=True):
    public, backup, package = paths(public)
    receipt = _receipt(public)
    if receipt.get('state') != 'installed' or digest(public) != receipt['files']['wrapper']:
        raise LaunchError('Public Unity launcher was changed or its installation is incomplete')
    if not backup.is_file() or _identity(backup) != receipt['original_identity']:
        raise LaunchError('Preserved original Editor identity changed')
    if full and digest(backup) != SUPPORTED_ELF_SHA256:
        raise LaunchError('Preserved original Editor bytes changed')
    return backup


def status(public, profile, *, settings_path=None):
    connected = False
    reason = 'Native scaling is not connected to this Editor.'
    try:
        if is_owned_candidate(public):
            verified_original(public, full=False)
            if settings_path is not None and _receipt(public).get('settings') != str(Path(settings_path).absolute()):
                raise LaunchError('This launcher is bound to a different settings file; rerun the app installer')
            connected = True
            reason = 'Saved preferences are read when Unity starts. Restart Unity to use a changed setting.'
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reason = 'Native launcher needs attention: ' + str(exc)
    return dict(connected=connected, available=connected, current_scale=None, live_apply=False,
                saved_mode='custom' if profile['override_enabled'] else 'unity-default',
                saved_percent=profile['ui_scale_percent'] if profile['override_enabled'] else None,
                restart_required=connected, production_applied=False, presented=False, message=reason)


def prepare(public, settings, product_manifest, manifest_sha256, stage, *, proof_only=False):
    """Compile/stage a reviewable package. No Editor-directory writes occur."""
    from . import core
    public, backup, package = paths(public)
    for path in (public, public.parent, backup, package):
        _safe(path, owner=True)
    proof_target = proof_only and public.is_relative_to(Path(tempfile.gettempdir()))
    if (core.is_lab_editor(public) and not proof_target) or public.name != 'Unity':
        raise LaunchError('Choose an installed public Editor outside disposable/app-owned folders')
    if backup.exists() or package.exists():
        raise LaunchError('A native integration/backup already exists; verify or restore it first')
    if not public.is_file() or not os.access(public, os.X_OK) or digest(public) != SUPPORTED_ELF_SHA256:
        raise LaunchError('Only the exact supported pristine Editor can be prepared')
    if not (public.parent / 'Data/Managed/UnityEditor.dll').is_file() or not (public.parent / 'Data/Resources').is_dir():
        raise LaunchError('Unity Data must remain beside the original executable')
    settings = Path(settings).absolute()
    if settings.resolve() != settings:
        raise LaunchError('Settings path must be canonical and nonsymlink')
    if any(c.isspace() or c == ':' for c in str(package / 'native.so')):
        raise LaunchError('Native delivery currently requires an Editor installation path without whitespace or colon')
    manifest = Path(product_manifest).absolute()
    if digest(manifest) != manifest_sha256 or manifest.stat().st_size > 65536:
        raise LaunchError('Product manifest does not match the independently reviewed pin')
    native = parse_json(manifest.read_bytes())
    if (native.get('constructor_contract') != 'product-profile-v1' or native.get('host_environment_abi') != 1
            or native.get('restore_host_on_refusal') is not True or native.get('original_sha256') != SUPPORTED_ELF_SHA256
            or native.get('public_editor') != str(public) or native.get('target_exe') != str(backup)
            or native.get('settings_path') != str(settings)):
        raise LaunchError('Product native build does not authorize this exact public/backup pair')
    library = _safe(native['library'])
    if digest(library) != native['library_sha256']:
        raise LaunchError('Product native DSO hash does not match its reviewed manifest')
    sources = [NATIVE_SOURCE / name for name in ('launcher.c', 'product_policy.c', 'product_policy.h', 'host_environment.h')]
    if not all(p.is_file() for p in sources):
        raise LaunchError('Distributable native launcher source package is incomplete')
    stage = _safe(stage)
    stage.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        original = _identity(public)
        config = dict(PUBLIC_EDITOR=str(public), ORIGINAL_EDITOR=str(backup), NATIVE_LIBRARY=str(package / 'native.so'),
                      SETTINGS_PATH=str(settings), ORIGINAL_SHA256=SUPPORTED_ELF_SHA256, NATIVE_SHA256=native['library_sha256'])
        header = ''.join('#define ' + key + ' ' + json.dumps(value) + '\n' for key, value in config.items())
        header += ''.join('#define ' + key + ' ' + str(value) + 'ULL\n' for key, value in
                          [('ORIGINAL_DEV', original['st_dev']), ('ORIGINAL_INO', original['st_ino']),
                           ('ORIGINAL_SIZE', original['st_size']), ('ORIGINAL_MTIME_SEC', original['st_mtime_ns'] // 1000000000),
                           ('ORIGINAL_MTIME_NSEC', original['st_mtime_ns'] % 1000000000)])
        (stage / 'config.h').write_text(header)
        for source in sources:
            shutil.copy2(source, stage / source.name)
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'json-c', 'openssl'], text=True))
        command = ['cc', '-O2', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                   '-I' + str(stage), str(stage / 'launcher.c'), str(stage / 'product_policy.c'),
                   *flags, '-o', str(stage / 'wrapper')]
        subprocess.run(command, check=True, capture_output=True, text=True)
        (stage / 'wrapper').chmod(0o755)
        shutil.copy2(library, stage / 'native.so')
        (stage / 'native.so').chmod(0o600)
        receipt = dict(schema=1, state='prepared', marker=MARKER.decode(), owner_uid=os.getuid(), proof_only=bool(proof_target),
                       public_editor=str(public), target_exe=str(backup), original_sha256=SUPPORTED_ELF_SHA256,
                       original_identity=original, original_mode=stat.S_IMODE(public.stat().st_mode),
                       constructor_contract='product-profile-v1', host_environment_abi=1, restore_host_on_refusal=True,
                       source_manifest_sha256=manifest_sha256, library_sha256=native['library_sha256'],
                       settings=str(settings), files={name: digest(stage / name) for name in ('wrapper', 'native.so')},
                       compiler_command=command, source_sha256={p.name: digest(p) for p in sources},
                       runtime_verified_percentages=native.get('runtime_verified_percentages', []),
                       production_applied=False, presented=False)
        atomic_json(stage / 'receipt.json', receipt)
        return receipt
    except BaseException:
        shutil.rmtree(stage)
        raise


def install(stage, preparation_sha256):
    """Explicit reversible disk operation; callers must authorize installation."""
    stage = _safe(stage, owner=True)
    if digest(stage / 'receipt.json') != preparation_sha256:
        raise LaunchError('Preparation receipt differs from its review pin')
    receipt = parse_json((stage / 'receipt.json').read_bytes())
    if receipt.get('state') != 'prepared' or receipt.get('schema') != 1 or receipt.get('marker') != MARKER.decode():
        raise LaunchError('Unrecognized prepared native package')
    public, backup, package = paths(receipt['public_editor'])
    if receipt.get('target_exe') != str(backup) or receipt.get('original_sha256') != SUPPORTED_ELF_SHA256:
        raise LaunchError('Prepared original identity differs')
    for path in (public, public.parent, backup, package):
        _safe(path, owner=True)
    if package.exists() or backup.exists() or _identity(public) != receipt['original_identity'] or digest(public) != SUPPORTED_ELF_SHA256:
        raise LaunchError('Editor/integration changed after preparation; nothing installed')
    for name in ('wrapper', 'native.so'):
        if digest(stage / name) != receipt['files'][name]:
            raise LaunchError('Prepared package changed; nothing installed')
    _running(public)
    package.mkdir(mode=0o700)
    promoted = False
    try:
        for name in ('wrapper', 'native.so'):
            shutil.copy2(stage / name, package / name)
        (package / 'wrapper').chmod(receipt['original_mode'])
        (package / 'native.so').chmod(0o600)
        atomic_json(package / 'receipt.json', receipt)
        os.link(public, backup)
        _sync(public.parent)
        fd, name = tempfile.mkstemp(prefix='.unity-scale-launcher-', dir=public.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write((package / 'wrapper').read_bytes())
                os.fchmod(stream.fileno(), receipt['original_mode'])
                stream.flush()
                os.fsync(stream.fileno())
            if digest(public) != SUPPORTED_ELF_SHA256 or not public.samefile(backup):
                raise LaunchError('Public Editor changed during installation')
            os.replace(name, public)
            promoted = True
            _sync(public.parent)
        finally:
            Path(name).unlink(missing_ok=True)
        receipt['state'] = 'installed'
        atomic_json(package / 'receipt.json', receipt)
        return status(public, dict(override_enabled=False, ui_scale_percent=150))
    except BaseException:
        if promoted and digest(public) == receipt['files']['wrapper'] and digest(backup) == SUPPORTED_ELF_SHA256:
            os.replace(backup, public)
        elif backup.exists() and public.exists() and public.samefile(backup):
            backup.unlink()
        if public.exists() and digest(public) == SUPPORTED_ELF_SHA256 and not backup.exists():
            shutil.rmtree(package)
        raise


def restore(public):
    """Restore only our exact wrapper+original pair; refuse updates/foreign edits."""
    public, backup, package = paths(public)
    receipt = _receipt(public)
    if digest(public) == SUPPORTED_ELF_SHA256 and receipt.get('state') == 'prepared':
        if backup.exists():
            if not public.samefile(backup):
                raise LaunchError('Incomplete installation backup differs; recovery left untouched')
            backup.unlink()
    else:
        if receipt.get('state') == 'installed':
            verified_original(public)
        elif (receipt.get('state') != 'prepared' or digest(public) != receipt['files']['wrapper']
              or _identity(backup) != receipt['original_identity'] or digest(backup) != SUPPORTED_ELF_SHA256):
            raise LaunchError('Interrupted integration cannot be safely restored')
        _running(backup)
        os.replace(backup, public)
        os.chmod(public, receipt['original_mode'])
    _sync(public.parent)
    if set(p.name for p in package.iterdir()) != {'receipt.json', 'native.so', 'wrapper'}:
        raise LaunchError('Original restored, but package contains unknown files; retained for review')
    shutil.rmtree(package)
    _sync(public.parent)
    return dict(restored=True, original_sha256=digest(public), public_editor=str(public))


def bundled_source():
    """Verify the frozen, distributable native source package, if present."""
    root = NATIVE_SOURCE / 'product'
    manifest = root / 'source-manifest.json'
    if not manifest.is_file():
        raise LaunchError('The reviewed native source package has not been bundled')
    value = parse_json(manifest.read_bytes())
    if value.get('constructor_contract') != 'product-profile-v1':
        raise LaunchError('Native source package contract differs')
    for relative, expected in value.get('files', {}).items():
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise LaunchError('Invalid native source manifest path')
        path = _safe(root / relative)
        if not path.is_relative_to(root) or digest(path) != expected:
            raise LaunchError('Frozen native source package changed: ' + relative)
    if 'build.py' not in value.get('files', {}):
        raise LaunchError('Native source builder is missing')
    return root


def prepare_supported(public, settings, stage):
    """Installer one-time setup using the bundled source; never launches Unity."""
    source = bundled_source()
    public, backup, _ = paths(public)
    # Build in a separate temporary directory so only the reviewable package
    # survives. The compiler reads the installed original without modifying it.
    with tempfile.TemporaryDirectory(prefix='unity-native-compile-') as temporary:
        output = Path(temporary) / 'native.so'
        command = ['/usr/bin/python3', str(source / 'build.py'), '--editor-source', str(public),
                   '--public-editor', str(public), '--target-exe', str(backup), '--settings', str(Path(settings).absolute()),
                   '--output', str(output)]
        subprocess.run(command, check=True, capture_output=True, text=True)
        manifest = output.parent / 'native.so.build/build.json'
        return prepare(public, settings, manifest, digest(manifest), stage)
