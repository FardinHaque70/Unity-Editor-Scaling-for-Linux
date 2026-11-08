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
    public, backup, package = paths(public)
    if package.exists():
        # Restoration can retain legacy/foreign audit leaves for review. They
        # do not turn the exact restored ELF into an installed launcher.
        if not backup.exists() and not (package / 'activation.json').exists():
            try:
                if digest(public) == SUPPORTED_ELF_SHA256:
                    return False
            except OSError:
                pass
        return True
    try:
        with public.open('rb') as stream:
            return MARKER in stream.read(1024 * 1024)
    except OSError:
        return False


def _receipt(public):
    public, backup, package = paths(public)
    if (package / 'activation.json').exists():
        return _v2_receipt(public)
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
    expected_wrapper = receipt['wrapper_sha256'] if receipt.get('schema') == 2 else receipt['files']['wrapper']
    if receipt.get('state', 'installed') != 'installed' or digest(public) != expected_wrapper:
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
    # The old preparation API remains for v1 recovery fixtures only. Shipping
    # installations use ConnectionPlan and never execute this compiler path.
    legacy_launcher = NATIVE_SOURCE / 'legacy-launcher-v1.c'
    sources = [legacy_launcher, *[NATIVE_SOURCE / name for name in ('product_policy.c', 'product_policy.h', 'host_environment.h')]]
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
            shutil.copy2(source, stage / ('launcher.c' if source == legacy_launcher else source.name))
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
    if receipt.get('schema') == 2:
        verified_original(public)
        _running(public)
        _running(backup)
        os.replace(backup, public)
        os.chmod(public, receipt['original_mode'])
        _sync(public.parent)
        # Do not remove legacy or foreign files during normal restoration.
        for name, expected in [('wrapper-v2', receipt['wrapper_sha256']), ('native-v2.so', receipt['library_sha256'])]:
            item = package / name
            if digest(item) != expected:
                raise LaunchError('Owned package changed during restore')
            item.unlink()
        (package / 'activation.json').unlink()
        if not any(package.iterdir()):
            package.rmdir()
        return dict(restored=True, original_sha256=digest(public), public_editor=str(public))
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


def _prepare_supported_legacy(public, settings, stage):
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


def bundled_binaries(bundle=None):
    """Verify distributable runtime binaries; users never need a compiler."""
    root = Path(bundle) if bundle is not None else NATIVE_SOURCE / 'prebuilt'
    root = _safe(root.absolute())
    manifest = _safe(root / 'manifest.json', owner=False)
    if not manifest.is_file() or manifest.stat().st_size > 65536:
        raise LaunchError('Prebuilt native runtime is missing; obtain the release AppImage')
    value = parse_json(manifest.read_bytes())
    if (value.get('schema') != 2 or value.get('constructor_contract') != 'product-profile-v2'
            or value.get('original_sha256') != SUPPORTED_ELF_SHA256):
        raise LaunchError('Prebuilt runtime compatibility manifest differs')
    for name in ('wrapper-v2', 'native-v2.so'):
        path = _safe(root / name)
        if not path.is_file() or digest(path) != value.get('files', {}).get(name):
            raise LaunchError('Prebuilt runtime changed: ' + name)
    return root, value


def _v2_receipt(public):
    public, backup, package = paths(public)
    for path in (public, backup, package):
        _safe(path, owner=True)
    activation = _safe(package / 'activation.json', owner=True)
    if not activation.is_file() or activation.stat().st_size > 65536:
        raise LaunchError('Native activation is missing or oversized')
    value = parse_json(activation.read_bytes())
    if (value.get('schema') != 2 or value.get('constructor_contract') != 'product-profile-v2'
            or value.get('owner_uid') != os.getuid() or value.get('public_editor') != str(public)
            or value.get('target_exe') != str(backup) or value.get('original_sha256') != SUPPORTED_ELF_SHA256
            or value.get('wrapper') != 'wrapper-v2' or value.get('library') != 'native-v2.so'
            or not isinstance(value.get('settings'), str) or not Path(value['settings']).is_absolute()):
        raise LaunchError('Native activation does not match this Editor')
    for name, key in [('wrapper-v2', 'wrapper_sha256'), ('native-v2.so', 'library_sha256')]:
        item = _safe(package / name, owner=True)
        if digest(item) != value.get(key):
            raise LaunchError('Owned native package changed: ' + name)
    return value


def _atomic_bytes(path, content, mode):
    _safe(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.unity-scale-stage-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _sync(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


class ConnectionPlan:
    """Prepared closed-Editor transaction, usable by the application installer.

    Legacy wrapper/DSO/receipt leaves remain until explicit manifest cleanup.
    The preserved original is never copied or rewritten.
    """
    def __init__(self, public, settings, *, bundle=None):
        self.public, self.backup, self.package = paths(public)
        self.settings = _safe(Path(settings).absolute())
        self.bundle, manifest = bundled_binaries(bundle)
        for path in (self.public, self.public.parent, self.backup, self.package):
            _safe(path, owner=True)
        if self.public.name != 'Unity':
            raise LaunchError('Choose the public executable named Unity')
        from .core import is_lab_editor
        if is_lab_editor(self.public):
            raise LaunchError('Choose an installed public Editor outside disposable/app-owned folders')
        if any(c.isspace() or c == ':' for c in str(self.package / 'native-v2.so')):
            raise LaunchError('Native delivery requires an Editor path without whitespace or colon')
        self.existing = is_owned_candidate(self.public)
        if self.existing:
            self.original = verified_original(self.public)
            self.old_receipt = _receipt(self.public)
        else:
            if self.backup.exists() or self.package.exists():
                raise LaunchError('An unknown integration already exists')
            self.original = self.public
            self.old_receipt = None
            if digest(self.original) != SUPPORTED_ELF_SHA256:
                raise LaunchError('Only the exact supported pristine Editor can be connected')
        if not (self.public.parent / 'Data/Managed/UnityEditor.dll').is_file() or not (self.public.parent / 'Data/Resources').is_dir():
            raise LaunchError('Unity Data must remain beside the preserved original')
        # Check BOTH inodes: a v1 wrapper execs the original backup inode.
        _running(self.public)
        _running(self.original)
        self.original_identity = _identity(self.original)
        self.old_package_mode = stat.S_IMODE(self.package.stat().st_mode) if self.package.exists() else None
        self.original_mode = (self.old_receipt or {}).get('original_mode', stat.S_IMODE(self.original.stat().st_mode))
        self.content = {name: (self.bundle / name).read_bytes() for name in ('wrapper-v2', 'native-v2.so')}
        self.activation = dict(schema=2, constructor_contract='product-profile-v2', owner_uid=os.getuid(),
                               public_editor=str(self.public), target_exe=str(self.backup), settings=str(self.settings),
                               original_sha256=SUPPORTED_ELF_SHA256, original_identity=self.original_identity,
                               original_mode=self.original_mode, wrapper='wrapper-v2', library='native-v2.so',
                               wrapper_sha256=manifest['files']['wrapper-v2'], library_sha256=manifest['files']['native-v2.so'],
                               host_environment_abi=1, restore_host_on_refusal=True)
        names = ('activation.json', 'wrapper-v2', 'native-v2.so')
        for name in names:
            _safe(self.package / name, owner=True)
        self.old_files = {name: ((self.package / name).read_bytes(), stat.S_IMODE((self.package / name).stat().st_mode))
                          if (self.package / name).exists() else None for name in names}
        self.old_public = self.public.read_bytes() if self.existing else None
        self.applied = False
        self.started = False

    def apply(self):
        if self.started:
            raise LaunchError('Connection plan already used')
        if _identity(self.original) != self.original_identity or digest(self.original) != SUPPORTED_ELF_SHA256:
            raise LaunchError('Original Editor changed after preparation')
        if self.existing and self.public.read_bytes() != self.old_public:
            raise LaunchError('Public launcher changed after preparation')
        _running(self.public)
        _running(self.original)
        self.started = True
        try:
            self.package.mkdir(mode=0o700, exist_ok=True)
            self.package.chmod(0o700)
            for name, content in self.content.items():
                _atomic_bytes(self.package / name, content, 0o755 if name == 'wrapper-v2' else 0o600)
            atomic_json(self.package / 'activation.json', self.activation)
            if not self.existing:
                os.link(self.public, self.backup)
                _sync(self.public.parent)
            _atomic_bytes(self.public, self.content['wrapper-v2'], self.original_mode)
            self.applied = True
            verified_original(self.public)
            return status(self.public, dict(override_enabled=False, ui_scale_percent=150), settings_path=self.settings)
        except BaseException:
            self.rollback()
            raise

    def rollback(self):
        if not self.started:
            return
        current_public = digest(self.public)
        expected_public = {hashlib.sha256(self.content['wrapper-v2']).hexdigest()}
        expected_public.add(hashlib.sha256(self.old_public).hexdigest() if self.existing else SUPPORTED_ELF_SHA256)
        if current_public not in expected_public:
            raise LaunchError('Public Editor changed during rollback; foreign file retained')
        if self.existing:
            if _identity(self.backup) != self.original_identity or digest(self.backup) != SUPPORTED_ELF_SHA256:
                raise LaunchError('Original changed during rollback; manual recovery required')
            _atomic_bytes(self.public, self.old_public, self.original_mode)
        elif self.backup.exists():
            if _identity(self.backup) != self.original_identity or digest(self.backup) != SUPPORTED_ELF_SHA256:
                raise LaunchError('Original changed during rollback; manual recovery required')
            os.replace(self.backup, self.public)
            _sync(self.public.parent)
        for name, old in self.old_files.items():
            item = self.package / name
            if old is None:
                item.unlink(missing_ok=True)
            else:
                _atomic_bytes(item, *old)
        if self.package.exists() and not any(self.package.iterdir()):
            self.package.rmdir()
        elif self.old_package_mode is not None:
            self.package.chmod(self.old_package_mode)
        self.applied = False
        self.started = False


def ensure_connected(public, store, *, bundle=None):
    """Connect or migrate a supported closed Editor to this persistent Store."""
    current = store.get_profile(public)
    existing = status(public, current, settings_path=store.path)
    if existing['connected']:
        receipt = _receipt(public)
        if receipt.get('schema') == 2:
            root, manifest = bundled_binaries(bundle)
            if receipt['wrapper_sha256'] == manifest['files']['wrapper-v2'] and receipt['library_sha256'] == manifest['files']['native-v2.so']:
                return existing
    plan = ConnectionPlan(public, store.path, bundle=bundle)
    plan.apply()
    return status(public, current, settings_path=store.path)


def prepare_supported(public, settings, stage):
    """Stage prebuilt v2 bytes without compiling or touching the Editor."""
    plan = ConnectionPlan(public, settings)
    stage = _safe(Path(stage).absolute())
    stage.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, content in plan.content.items():
        _atomic_bytes(stage / name, content, 0o755 if name == 'wrapper-v2' else 0o600)
    atomic_json(stage / 'activation.json', plan.activation)
    return plan.activation


def cleanup_legacy_connection(public):
    """Remove unchanged v1 receipt-owned leaves after caller's artifact proof.

    This is deliberately separate from connection promotion and never removes
    unknown files, the active v2 runtime, or the original executable.
    """
    public, backup, package = paths(public)
    current = _v2_receipt(public)
    verified_original(public)
    _running(public)
    _running(backup)
    file = package / 'receipt.json'
    if not file.exists():
        return []
    _safe(file, owner=True)
    if file.stat().st_size > 65536:
        raise LaunchError('Legacy ownership receipt exceeds its size limit')
    previous = parse_json(file.read_bytes())
    if (previous.get('schema') != 1 or previous.get('marker') != MARKER.decode()
            or previous.get('owner_uid') != os.getuid() or previous.get('public_editor') != str(public)
            or previous.get('target_exe') != str(backup) or previous.get('original_sha256') != SUPPORTED_ELF_SHA256
            or previous.get('original_identity') != current['original_identity']):
        raise LaunchError('Legacy ownership receipt differs; old files retained')
    for name in ('wrapper', 'native.so'):
        item = _safe(package / name, owner=True)
        if not item.is_file() or digest(item) != previous.get('files', {}).get(name):
            raise LaunchError('Legacy package changed; old files retained')
    for name in ('wrapper', 'native.so', 'receipt.json'):
        (package / name).unlink()
    _sync(package)
    return ['wrapper', 'native.so', 'receipt.json']
