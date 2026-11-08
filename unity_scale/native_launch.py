"""Verified ordinary exec environment; no process launch or native scale choice.

The native constructor reads the current settings once. Default may retain a
neutral loader so a later original-ELF OpenProject child can reread the profile.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SUPPORTED_ELF_SHA256 = 'd5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec'
HOST_KEY = 'UNITY_EDITOR_SCALING_HOST_ENV'
SETTINGS_KEY = 'UNITY_EDITOR_SCALING_SETTINGS'
EDITOR_KEY = 'UNITY_EDITOR_SCALING_PUBLIC_EDITOR'
HOST_VARIABLES = ('GDK_SCALE', 'GDK_DPI_SCALE', 'GDK_BACKEND')
BYPASS = {'-batchmode', '-nographics', '-version', '--version', '-help', '--help',
          '-returnlicense', '-manuallicensefile', '-createmanualactivationfile'}


class LaunchError(ValueError):
    pass


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise LaunchError('Duplicate metadata key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(LaunchError('Nonfinite JSON')))
    except (ValueError, UnicodeError) as exc:
        raise LaunchError('Invalid launch metadata') from exc


def digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise LaunchError('Expected a regular file')
        result = hashlib.sha256()
        while block := os.read(fd, 1024 * 1024):
            result.update(block)
        after = os.fstat(fd)
        if any(getattr(before, key) != getattr(after, key) for key in
               ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
            raise LaunchError('File changed during verification')
        return result.hexdigest()
    finally:
        os.close(fd)


def canonical(path):
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise LaunchError('An absolute path is required')
    return str(target.resolve(strict=True))


def restore_host_environment(inherited):
    env = dict(inherited)
    raw = env.get(HOST_KEY)
    if raw is None:
        return env
    if len(raw.encode()) > 4096:
        raise LaunchError('Original host envelope exceeds ABI1 limit')
    value = parse_json(raw)
    if (not isinstance(value, dict) or set(value) != {'abi', *HOST_VARIABLES}
            or type(value.get('abi')) is not int or value['abi'] != 1):
        raise LaunchError('Invalid ABI1 original host envelope')
    for key in HOST_VARIABLES:
        item = value[key]
        if item is not None and (not isinstance(item, str) or len(item.encode()) > 512 or '\0' in item):
            raise LaunchError('Invalid original host variable')
    for key in HOST_VARIABLES:
        if value[key] is None:
            env.pop(key, None)
        else:
            env[key] = value[key]
    return env


def strip_own_preload(env, library):
    """Remove only exact tokens/same-inode aliases of our DSO, keeping foreign order."""
    env = dict(env)
    parts = re.findall(r'[^:\s]+', env.get('LD_PRELOAD', ''))
    kept = []
    for part in parts:
        try:
            own = part == str(library) or ('/' in part and os.path.samefile(part, library))
        except OSError:
            own = part == str(library)
        if not own:
            kept.append(part)
    if kept:
        env['LD_PRELOAD'] = ':'.join(kept)
    elif parts:
        env.pop('LD_PRELOAD', None)
    return env


def verify_manifest(path, expected_sha256):
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise LaunchError('A reviewed external manifest SHA256 pin is required')
    path = Path(path).absolute()
    if path.is_symlink() or path.stat().st_size > 65536 or digest(path) != expected_sha256:
        raise LaunchError('Manifest identity refused')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise LaunchError('Manifest changed during verification')
    value = parse_json(raw)
    if (not isinstance(value, dict) or value.get('constructor_contract') != 'product-profile-v1'
            or value.get('host_environment_abi') != 1 or value.get('restore_host_on_refusal') is not True
            or value.get('original_sha256') != SUPPORTED_ELF_SHA256):
        raise LaunchError('Unverified product constructor/ELF/environment contract')
    for key in ('public_editor', 'target_exe', 'library'):
        if not isinstance(value.get(key), str) or canonical(value[key]) != value[key]:
            raise LaunchError('Manifest needs canonical ' + key)
    if not re.fullmatch('[0-9a-f]{64}', str(value.get('library_sha256', ''))):
        raise LaunchError('Native library SHA256 is missing')
    return value


@dataclass(frozen=True)
class LaunchPlan:
    executable: str
    argv: tuple = field(repr=False)
    environment: dict = field(repr=False)
    mode: str = 'neutral-loader; constructor reads saved choice'
    note: str = 'No current-scale or presented-frame acknowledgement'


def plan_launch(store, public_editor, argv, inherited, *, executable=None,
                manifest=None, manifest_sha256=None, preload_alias=None, kind='editor'):
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(a, str) or '\0' in a for a in argv):
        raise LaunchError('A literal complete argv vector is required')
    if any(not isinstance(k, str) or not isinstance(v, str) or '\0' in k + v or '=' in k for k, v in inherited.items()):
        raise LaunchError('Invalid environment')
    receipt = verify_manifest(manifest, manifest_sha256)
    public = canonical(public_editor)
    target = canonical(executable if executable is not None else public)
    if receipt['public_editor'] != public or receipt['target_exe'] != target:
        raise LaunchError('Manifest public/actual executable pair differs')
    if digest(target) != SUPPORTED_ELF_SHA256 or digest(receipt['library']) != receipt['library_sha256']:
        raise LaunchError('Editor/native library SHA256 refused')
    env = strip_own_preload(restore_host_environment(inherited), receipt['library'])
    bypass = kind in {'helper', 'licensing'} or any(a.lower() in BYPASS for a in argv[1:])
    bypass |= any(a.lower() == '-name' and i + 1 < len(argv) and argv[i + 1].startswith('LightBakerWorker') for i, a in enumerate(argv))
    if kind not in {'editor', 'helper', 'licensing'}:
        raise LaunchError('Unknown process kind')
    if bypass:
        return LaunchPlan(target, tuple(argv), env, 'helper-bypass')
    library = str(Path(preload_alias).absolute()) if preload_alias is not None else receipt['library']
    if re.search(r'[:\s\x00]', library) or not os.path.samefile(library, receipt['library']):
        raise LaunchError('Loader requires a whitespace/colon-free verified DSO path')
    settings = str(Path(store.path).absolute())
    if receipt.get('settings_path') != settings:
        raise LaunchError('Native constructor settings path differs from Store.path')
    if Path(settings).resolve() != Path(settings):
        raise LaunchError('Settings path cannot contain symlinks')
    # The launcher carries identity only. No MODE/PERCENT or GDK/renderer override.
    for key in ('UNITY_NATIVE_STARTUP_MODE', 'UNITY_NATIVE_STARTUP_PERCENT', 'UNITY_NATIVE_STARTUP_ENABLE'):
        env.pop(key, None)
    envelope = dict(abi=1, **{key: env.get(key) for key in HOST_VARIABLES})
    env[HOST_KEY] = json.dumps(envelope, separators=(',', ':'), ensure_ascii=True)
    restore_host_environment(env)  # Validate bounded ABI, including original host values.
    env.update({SETTINGS_KEY: settings, EDITOR_KEY: public})
    env['LD_PRELOAD'] = library + (':' + env['LD_PRELOAD'] if env.get('LD_PRELOAD') else '')
    return LaunchPlan(target, tuple(argv), env)
