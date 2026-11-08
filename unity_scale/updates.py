"""Explicit, signed AppImage updates. Importing this module never uses the network."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import core

REPOSITORY = 'FardinHaque70/Unity-Editor-Scaling-for-Linux'
API = 'https://api.github.com/repos/' + REPOSITORY + '/releases'
FILENAME = 'Unity-Editor-Scaling-for-Linux-x86_64.AppImage'
MAX_IMAGE = 1024 * 1024 * 1024
TIMEOUT = 20


class UpdateError(core.AppError):
    pass


class Cancelled(UpdateError):
    def __init__(self):
        super().__init__('Update cancelled.')


def version_key(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.(0|[1-9]\d*))?', value or '')
    if not match:
        raise UpdateError('Unsupported release version: ' + str(value))
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), 1 if rc is None else 0, int(rc or 0)


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def asset_url(url):
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme == 'https' and parts.netloc == 'github.com' and not parts.query and not parts.fragment
            and parts.path.startswith('/' + REPOSITORY + '/releases/download/')
            and len(parts.path.split('/')) == 7)


def api_asset_url(url):
    if not isinstance(url, str):
        return False
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme == 'https' and parts.netloc == 'api.github.com'
            and not parts.query and not parts.fragment
            and re.fullmatch('/repos/' + re.escape(REPOSITORY) + '/releases/assets/[1-9][0-9]*', parts.path) is not None)


def _network_url(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme == 'https' and not p.username and not p.password and (p.netloc in {
        'release-assets.githubusercontent.com', 'objects.githubusercontent.com'} or
        (p.netloc == 'github.com' and asset_url(url)) or
        (p.netloc == 'api.github.com' and p.path == '/repos/' + REPOSITORY + '/releases') or api_asset_url(url))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _network_url(newurl):
            raise UpdateError('The release redirected outside official GitHub assets.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubTransport:
    """Production HTTPS transport; tests inject an independent in-memory transport."""
    def open(self, url):
        if not _network_url(url):
            raise UpdateError('Refusing a release URL outside GitHub.')
        request = urllib.request.Request(url, headers={'User-Agent': 'Unity-Editor-Scaling/' + core.VERSION,
            'Accept': 'application/vnd.github+json' if urllib.parse.urlsplit(url).path == '/repos/' + REPOSITORY + '/releases' else 'application/octet-stream'})
        try:
            return urllib.request.build_opener(_SafeRedirect()).open(request, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (403, 429):
                raise UpdateError('GitHub rate limit reached. Try again later.') from exc
            raise UpdateError('GitHub could not provide the update (HTTP %s).' % exc.code) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise UpdateError('Could not reach GitHub. Check your connection and try again.') from exc


def _bytes(transport, url, limit, cancel):
    data = bytearray()
    with transport.open(url) as response:
        while True:
            _cancel(cancel)
            chunk = response.read(min(65536, limit + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            if len(data) > limit:
                raise UpdateError('The release response is larger than expected.')


def _object(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise UpdateError('Release metadata contains duplicate keys.')
            value[key] = item
        return value
    try:
        return json.loads(data, object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        raise UpdateError('Release metadata is invalid.') from exc


def verify_signature(manifest, signature, *, helper=None, public_key=None):
    if len(signature) != 64:
        raise UpdateError('The release signature is invalid.')
    helper = Path(helper or core.ROOT / 'libexec/unity-scale-update-helper')
    public_key = Path(public_key or core.ROOT / 'resources/update-public-key.pem')
    if not helper.is_file() or not public_key.is_file():
        raise UpdateError('This build does not include the signed update verifier.')
    with tempfile.TemporaryDirectory(prefix='unity-scale-signature-') as directory:
        base = Path(directory)
        (base / 'manifest').write_bytes(manifest)
        (base / 'signature').write_bytes(signature)
        result = subprocess.run([str(helper), 'verify', str(public_key), str(base / 'manifest'),
                                 str(base / 'signature')], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=10, check=False)
        if result.returncode:
            raise UpdateError('The release signature could not be verified. No update was installed.')


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    url: str
    size: int
    sha256: str
    manifest: bytes
    signature: bytes


@dataclass
class PreparedUpdate:
    release: Release
    target: Path
    directory: Path
    staged: Path

    def cleanup(self):
        shutil.rmtree(self.directory, ignore_errors=True)


def check(*, current=None, transport=None, cancel=None, verifier=None):
    """List releases: prerelease clients accept rc/stable; stable clients stable only."""
    current = current or core.VERSION
    current_key = version_key(current)
    transport = transport or GitHubTransport()
    candidates = []
    for page in range(1, 6):
        values = _object(_bytes(transport, API + '?per_page=100&page=' + str(page), 4 * 1024 * 1024, cancel))
        if not isinstance(values, list):
            raise UpdateError('GitHub returned an invalid release list.')
        for release in values:
            if not isinstance(release, dict) or release.get('draft'):
                continue
            try:
                key = version_key(release.get('tag_name'))
            except UpdateError:
                continue
            if key <= current_key or (current_key[3] and (not key[3] or release.get('prerelease'))):
                continue
            candidates.append((key, release))
        if len(values) < 100:
            break
    if not candidates:
        return None
    _key, release = max(candidates, key=lambda item: item[0])
    assets = {}
    for asset in release.get('assets', []):
        name, url = asset.get('name'), asset.get('browser_download_url', '')
        if name in (FILENAME, 'release.json', 'release.json.sig'):
            if name in assets or not asset_url(url) or urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit('/', 1)[1]) != name:
                raise UpdateError('The release contains invalid asset URLs.')
            # GitHub's immutable asset API avoids the browser download path,
            # which can fail behind otherwise working GitHub HTTPS gateways.
            # Both metadata identities stay restricted to this repository; the
            # payload is still accepted only after signature/hash verification.
            api_url = asset.get('url')
            if api_url is not None and not api_asset_url(api_url):
                raise UpdateError('The release contains an invalid API asset URL.')
            assets[name] = api_url or url
    if set(assets) != {FILENAME, 'release.json', 'release.json.sig'}:
        raise UpdateError('This release is missing its signed update assets.')
    manifest = _bytes(transport, assets['release.json'], 16384, cancel)
    signature = _bytes(transport, assets['release.json.sig'], 64, cancel)
    _cancel(cancel)
    (verifier or verify_signature)(manifest, signature)
    value = _object(manifest)
    required = {'schema', 'version', 'channel', 'architecture', 'filename', 'size', 'sha256'}
    if (not isinstance(value, dict) or set(value) != required or type(value['schema']) is not int or value['schema'] != 1
            or value['version'] != release['tag_name'].removeprefix('v')
            or value['channel'] != ('stable' if _key[3] else 'prerelease')
            or value['architecture'] != 'x86_64' or value['filename'] != FILENAME
            or type(value['size']) is not int or not 0 < value['size'] <= MAX_IMAGE
            or not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256'])):
        raise UpdateError('The signed release manifest is incompatible with this application.')
    return Release(value['version'], str(release.get('body') or '')[:64000], assets[FILENAME],
                   value['size'], value['sha256'], manifest, signature)


def managed_image():
    from . import private_store
    return core._xdg('XDG_DATA_HOME', '.local/share') / private_store.APP_DIR / 'application.AppImage'


def _boot_id():
    value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
        raise UpdateError('Cannot establish the update process boot identity.')
    return value


def _process_start(pid):
    # comm can contain whitespace and parentheses. Field22 follows the final
    # closing parenthesis; a PID by itself is never enough after reuse/reboot.
    fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    value = fields[19]
    if not value.isdecimal():
        raise UpdateError('Cannot establish the update process birth identity.')
    return value


def _cleanup_abandoned_downloads(target):
    """Remove only verified dead-owner pre-helper stages, under helper lock."""
    import stat
    from .private_store import safe_root
    removed = 0
    boot = _boot_id()
    for directory in target.parent.glob('.update-*'):
        if (directory / 'transaction.json').exists() or not (directory / 'owner.json').exists():
            continue
        safe_root(directory)
        ds = directory.lstat()
        if not stat.S_ISDIR(ds.st_mode) or ds.st_uid != os.getuid() or ds.st_mode & 0o077:
            raise UpdateError('Unsafe update staging directory; files were preserved.')
        owner = directory / 'owner.json'
        safe_root(owner)
        metadata = owner.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o022 or metadata.st_size > 2048):
            raise UpdateError('Unsafe update owner record; files were preserved.')
        value = _object(owner.read_bytes())
        if (not isinstance(value, dict) or set(value) != {'schema', 'pid', 'boot_id', 'start_time', 'target'}
                or type(value['schema']) is not int or value['schema'] != 1
                or type(value['pid']) is not int or not 1 <= value['pid'] <= 2147483647
                or not isinstance(value['boot_id'], str) or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value['boot_id'])
                or not isinstance(value['start_time'], str) or not value['start_time'].isdecimal()
                or value['target'] != str(target)):
            raise UpdateError('Invalid update owner record; files were preserved.')
        if value['boot_id'] == boot:
            try:
                if _process_start(value['pid']) == value['start_time']:
                    continue
            except FileNotFoundError:
                pass
            except (PermissionError, ProcessLookupError):
                # Unable to prove death: retain rather than interfere with a
                # possible active downloader in another process namespace.
                continue
        allowed = {'owner.json', 'new.AppImage', 'release.json', 'release.json.sig',
                   'public-key.pem', 'update-helper'}
        children = list(directory.iterdir())
        for child in children:
            safe_root(child)
            cs = child.lstat()
            if (child.name not in allowed or not stat.S_ISREG(cs.st_mode)
                    or cs.st_uid != os.getuid() or cs.st_mode & 0o022):
                raise UpdateError('Unexpected files in abandoned update; files were preserved.')
        for child in children:
            child.unlink()
        directory.rmdir()
        removed += 1
    if removed:
        from .native_backend import _sync
        _sync(target.parent)
    return removed


def prepare(release, *, target=None, transport=None, cancel=None, progress=None):
    target = Path(target or managed_image()).absolute()
    if not target.is_file() or target.is_symlink() or target.stat().st_uid != os.getuid():
        raise UpdateError('Install this AppImage for your user before updating it.')
    directory = Path(tempfile.mkdtemp(prefix='.update-', dir=target.parent))
    staged = directory / 'new.AppImage'
    try:
        from .private_store import atomic_json
        atomic_json(directory / 'owner.json', dict(schema=1, pid=os.getpid(),
            boot_id=_boot_id(), start_time=_process_start(os.getpid()), target=str(target)))
        sha = hashlib.sha256()
        count = 0
        with (transport or GitHubTransport()).open(release.url) as response, staged.open('xb') as output:
            while True:
                _cancel(cancel)
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > release.size:
                    raise UpdateError('The downloaded update is larger than its signed size.')
                output.write(chunk)
                sha.update(chunk)
                if progress:
                    progress(count, release.size)
            output.flush()
            os.fsync(output.fileno())
        _cancel(cancel)
        if count != release.size or sha.hexdigest() != release.sha256:
            raise UpdateError('The downloaded update failed verification. No update was installed.')
        staged.chmod(0o700)
        (directory / 'release.json').write_bytes(release.manifest)
        (directory / 'release.json.sig').write_bytes(release.signature)
        return PreparedUpdate(release, target, directory, staged)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def restart(prepared):
    """Launch a self-contained helper outside the mounted image, then caller quits."""
    from .user_install import check_update_ready
    check_update_ready()
    if prepared.target.with_name(prepared.target.name + '.rollback').exists():
        raise UpdateError('A previous update rollback is still present. Restart the installed app before updating again.')
    helper = core.ROOT / 'libexec/unity-scale-update-helper'
    detached = prepared.directory / 'update-helper'
    shutil.copyfile(helper, detached)
    detached.chmod(0o700)
    key = prepared.directory / 'public-key.pem'
    shutil.copyfile(core.ROOT / 'resources/update-public-key.pem', key)
    token = secrets.token_hex(32)
    ack = prepared.directory / 'healthy'
    process = subprocess.Popen([str(detached), 'apply', str(os.getpid()), str(prepared.target),
        str(prepared.staged), str(prepared.directory / 'release.json'),
        str(prepared.directory / 'release.json.sig'), str(key), str(ack), token, prepared.release.version],
        start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process.pid


def acknowledge(path, token):
    path = Path(path).absolute()
    image = Path(os.environ.get('APPIMAGE', '')).absolute()
    if (not re.fullmatch('[0-9a-f]{64}', token) or path.name != 'healthy'
            or not path.parent.name.startswith('.update-') or path.parent.parent != image.parent
            or path.parent.is_symlink() or path.parent.stat().st_uid != os.getuid()
            or path.parent.stat().st_mode & 0o077):
        raise UpdateError('Invalid post-update health acknowledgement.')
    with path.open('x') as stream:
        os.chmod(path, 0o600)
        stream.write(token)
        stream.flush()
        os.fsync(stream.fileno())


def host_environment():
    """Leave the old AppImage runtime before starting another executable."""
    environment = os.environ.copy()
    for key in ('APPIMAGE', 'APPDIR', 'ARGV0', 'PYTHONHOME', 'PYTHONPATH', 'GI_TYPELIB_PATH',
                'GIO_MODULE_DIR', 'GIO_EXTRA_MODULES', 'GTK_DATA_PREFIX', 'GSETTINGS_SCHEMA_DIR', 'SSL_CERT_FILE',
                'GDK_PIXBUF_MODULEDIR', 'GDK_PIXBUF_MODULE_FILE'):
        environment.pop(key, None)
    for key in ('LD_LIBRARY_PATH', 'PATH', 'XDG_DATA_DIRS', 'FONTCONFIG_FILE', 'FONTCONFIG_PATH'):
        saved = environment.pop('UNITY_SCALE_HOST_' + key, None)
        if saved:
            environment[key] = saved
        elif key != 'PATH':
            environment.pop(key, None)
    return environment


def _recovery_editors_closed(store):
    # An interrupted native migration may have a temporarily incomplete receipt.
    # Check executable inodes directly here; installation-journal recovery will
    # verify/restore those bytes after the previous image has been selected.
    from . import native_backend
    from .user_install import _app_closed, _editors, migration_document
    _app_closed(store)
    document = migration_document(store)
    for public in _editors(store, document):
        for executable in native_backend.paths(public)[:2]:
            if executable.is_file():
                native_backend._running(executable)


def recover_interrupted_update(*, store=None, execute=None, verifier=None, preflight=None):
    """Recover a durable update transaction after helper/process/power failure.

    The directory lock is shared with the native helper. A live helper owns
    recovery until it exits; a stale transaction is never accepted on filenames
    alone. Signature, payload hashes, ownership and the health token all bind the
    decision. Editor/native migration recovery is performed by --install-user
    after restoring the previous AppImage.
    """
    import fcntl
    import stat
    from .private_store import safe_root
    from .native_backend import digest, _sync
    store = store or core.Store()
    target = safe_root(store.data_dir / 'application.AppImage')
    if not target.parent.exists():
        return {'state': 'none'}
    rollback = target.with_name(target.name + '.rollback')
    descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'active'}
        abandoned = _cleanup_abandoned_downloads(target)
        candidates = [p for p in target.parent.glob('.update-*') if (p / 'transaction.json').exists()]
        if not candidates:
            if rollback.exists():
                raise UpdateError('An update rollback has no recovery record. Its files were preserved; repair the managed installation before updating.')
            return {'state': 'none', 'abandoned_downloads_removed': abandoned}
        if len(candidates) != 1:
            raise UpdateError('Multiple update recovery records need inspection; no files were changed.')
        directory = safe_root(candidates[0])
        def owned(path, *, directory=False):
            s = path.lstat()
            kind = stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)
            if not kind or s.st_uid != os.getuid() or s.st_mode & (0o077 if directory else 0o022):
                raise UpdateError('Unsafe update recovery file; no files were changed.')
        owned(directory, directory=True)
        journal = directory / 'transaction.json'
        owned(journal)
        if journal.stat().st_size > 2048:
            raise UpdateError('The update recovery record is oversized.')
        value = _object(journal.read_bytes())
        required = {'schema', 'old_sha256', 'new_sha256', 'version', 'token'}
        if (not isinstance(value, dict) or set(value) != required or type(value['schema']) is not int or value['schema'] != 1
                or any(not isinstance(value[k], str) or not re.fullmatch('[0-9a-f]{64}', value[k])
                       for k in ('old_sha256', 'new_sha256', 'token'))):
            raise UpdateError('The update recovery record is invalid.')
        version_key(value['version'])
        manifest = directory / 'release.json'
        signature = directory / 'release.json.sig'
        owned(manifest);owned(signature)
        if manifest.stat().st_size > 16384 or signature.stat().st_size != 64:
            raise UpdateError('The update recovery signature metadata is invalid.')
        data = manifest.read_bytes()
        (verifier or verify_signature)(data, signature.read_bytes())
        signed = _object(data)
        if (not isinstance(signed, dict) or set(signed) != {'schema', 'version', 'channel', 'architecture', 'filename', 'size', 'sha256'}
                or type(signed['schema']) is not int or signed['schema'] != 1
                or signed['version'] != value['version'] or signed['sha256'] != value['new_sha256']
                or signed['channel'] != ('stable' if version_key(value['version'])[3] else 'prerelease')
                or signed['architecture'] != 'x86_64' or signed['filename'] != FILENAME
                or type(signed['size']) is not int or not 0 < signed['size'] <= MAX_IMAGE):
            raise UpdateError('The signed update and recovery record do not match.')
        owned(target)
        current = digest(target)
        if current not in (value['old_sha256'], value['new_sha256']):
            raise UpdateError('The application changed during an interrupted update; all recovery files were preserved.')
        if current == value['new_sha256'] and target.stat().st_size != signed['size']:
            raise UpdateError('The update payload size changed; all recovery files were preserved.')
        if rollback.exists():
            owned(rollback)
            if digest(rollback) != value['old_sha256']:
                raise UpdateError('The rollback image does not match its recovery record.')
        healthy = directory / 'healthy'
        acknowledged = False
        if healthy.exists():
            owned(healthy)
            acknowledged = healthy.stat().st_size == 64 and healthy.read_text() == value['token']
        allowed = {'new.AppImage', 'release.json', 'release.json.sig', 'public-key.pem',
                   'healthy', 'update-helper', 'transaction.json', 'owner.json'}
        if any(p.name not in allowed for p in directory.iterdir()):
            raise UpdateError('Unexpected files in update recovery directory; all files were preserved.')
        for p in directory.iterdir():
            owned(p)
        # A successful health ACK can survive before helper cleanup. A failed
        # candidate must restore the previous image, with all Editors closed.
        restore = current == value['new_sha256'] and not acknowledged
        if restore:
            if not rollback.exists():
                raise UpdateError('The interrupted update has no verified rollback image.')
            (preflight or _recovery_editors_closed)(store)
            os.replace(rollback, target)
            _sync(target.parent)
        elif rollback.exists():
            rollback.unlink()
            _sync(target.parent)
        for p in directory.iterdir():
            p.unlink()
        directory.rmdir()
        _sync(target.parent)
        if restore:
            # Explicit installer startup restores the matching native bundle
            # and integration after the executable swap. No Unity is launched.
            (execute or os.execve)(str(target), [str(target), '--install-user', '--recover-update'], host_environment())
            return {'state': 'restored'}
        return {'state': 'committed' if acknowledged and current == value['new_sha256'] else 'cancelled'}
    finally:
        os.close(descriptor)
