"""Offline update policy, cancellation, tamper and real Ed25519 verifier tests."""
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from unity_scale import updates

BASE = 'https://github.com/' + updates.REPOSITORY + '/releases/download/'


class Transport:
    def __init__(self, values):
        self.values = values
        self.requested = []

    def open(self, url):
        self.requested.append(url)
        return io.BytesIO(self.values[url])


def fixture(version='0.5.0-rc.1', image=b'inert appimage fixture'):
    manifest = json.dumps(dict(schema=1, version=version,
        channel='prerelease' if '-rc.' in version else 'stable', architecture='x86_64',
        filename=updates.FILENAME, size=len(image), sha256=hashlib.sha256(image).hexdigest())).encode()
    release = dict(tag_name='v' + version, prerelease='-rc.' in version, draft=False, body='Notes', assets=[
        dict(name=name, browser_download_url=BASE + 'v' + version + '/' + name)
        for name in (updates.FILENAME, 'release.json', 'release.json.sig')])
    values = {updates.API + '?per_page=100&page=1': json.dumps([release]).encode(),
              BASE + 'v' + version + '/release.json': manifest,
              BASE + 'v' + version + '/release.json.sig': b's' * 64,
              BASE + 'v' + version + '/' + updates.FILENAME: image}
    return release, values


class UpdateTests(unittest.TestCase):
    def check(self, values, current='0.4.0-rc.1', verifier=lambda _m, _s: None):
        return updates.check(current=current, transport=Transport(values), verifier=verifier)

    def test_version_policy(self):
        _, values = fixture()
        self.assertIsNotNone(self.check(values))
        self.assertIsNone(self.check(values, current='0.4.0'))
        _, values = fixture('0.4.0')
        self.assertIsNotNone(self.check(values))
        self.assertIsNone(self.check(values, current='0.4.0'))
        with self.assertRaises(updates.UpdateError):
            updates.version_key('0.4.0-rc.01')

    def test_release_list_not_latest(self):
        pre, values = fixture('0.6.0-rc.1')
        stable, stable_values = fixture('0.5.0')
        values.update(stable_values)
        values[updates.API + '?per_page=100&page=1'] = json.dumps([pre, stable]).encode()
        self.assertEqual(self.check(values).version, '0.6.0-rc.1')
        self.assertEqual(self.check(values, current='0.4.0').version, '0.5.0')

    def test_reject_manifest_tamper(self):
        _, values = fixture()
        def rejected(_manifest, _signature):
            raise updates.UpdateError('bad signature')
        with self.assertRaises(updates.UpdateError):
            self.check(values, verifier=rejected)
        key = BASE + 'v0.5.0-rc.1/release.json'
        doc = json.loads(values[key]);doc['architecture'] = 'aarch64'
        values[key] = json.dumps(doc).encode()
        with self.assertRaises(updates.UpdateError):
            self.check(values)

    def test_reject_duplicate_manifest_keys(self):
        _, values = fixture()
        key = BASE + 'v0.5.0-rc.1/release.json'
        values[key] = values[key].replace(b'{', b'{"schema":1,', 1)
        with self.assertRaises(updates.UpdateError):
            self.check(values)

    def test_reject_external_asset(self):
        release, values = fixture()
        release['assets'][0]['browser_download_url'] = 'https://evil.example/app.AppImage'
        values[updates.API + '?per_page=100&page=1'] = json.dumps([release]).encode()
        with self.assertRaises(updates.UpdateError):
            self.check(values)
        self.assertFalse(updates._network_url('http://github.com/a'))
        self.assertFalse(updates._network_url('https://github.com.evil.example/a'))

    def test_verified_stage_and_cleanup_on_tamper_cancel(self):
        _, values = fixture()
        release = self.check(values)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'application.AppImage'
            target.write_bytes(b'old')
            prepared = updates.prepare(release, target=target, transport=Transport(values))
            self.assertEqual(prepared.directory.parent, target.parent)
            self.assertEqual(prepared.staged.read_bytes(), b'inert appimage fixture')
            self.assertEqual(target.read_bytes(), b'old')
            prepared.cleanup()
            values[release.url] = b'bad'
            with self.assertRaises(updates.UpdateError):
                updates.prepare(release, target=target, transport=Transport(values))
            self.assertEqual(list(target.parent.iterdir()), [target])
            cancel = threading.Event();cancel.set()
            with self.assertRaises(updates.Cancelled):
                updates.prepare(release, target=target, transport=Transport(values), cancel=cancel)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_download_cancel_during_progress(self):
        _, values = fixture()
        release = self.check(values)
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'application.AppImage';target.write_bytes(b'old')
            with self.assertRaises(updates.Cancelled):
                updates.prepare(release, target=target, transport=Transport(values), cancel=cancel,
                                progress=lambda *_: cancel.set())
            self.assertEqual(list(target.parent.iterdir()), [target])


class BootstrapTests(unittest.TestCase):
    def test_initial_install_managed_noop_and_old_download_dispatch(self):
        from unity_scale.__main__ import bootstrap_appimage
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data = base / 'data';state = base / 'state';data.mkdir();state.mkdir()
            store = SimpleNamespace(data_dir=data, state_dir=state)
            source = base / 'download.AppImage';source.write_bytes(b'inert external')
            calls = []
            bootstrap_appimage(store=store, source=source, installer=lambda *a, **k: calls.append((a, k)))
            self.assertEqual(len(calls), 1)
            managed = data / 'application.AppImage';managed.write_bytes(b'inert installed')
            bootstrap_appimage(store=store, source=managed, installer=lambda *_a, **_k: self.fail('daily installation'))
            (state / 'installation.json').write_text(json.dumps(dict(version='9.0.0', image=str(managed),
                image_sha256=hashlib.sha256(managed.read_bytes()).hexdigest())))
            executions = []
            bootstrap_appimage(store=store, source=source, installer=lambda *_a, **_k: self.fail('downgrade'),
                               execute=lambda *args: executions.append(args))
            self.assertEqual(executions[0][:2], (str(managed), [str(managed), 'gui']))
            managed.write_bytes(b'tamper')
            with self.assertRaises(updates.core.AppError):
                bootstrap_appimage(store=store, source=source, execute=lambda *_a: self.fail('tampered execution'))

    def test_host_environment_removes_old_mount(self):
        with patch.dict('os.environ', {'APPDIR': '/old/mount', 'PYTHONHOME': '/old/python',
                'LD_LIBRARY_PATH': '/old/lib', 'UNITY_SCALE_HOST_LD_LIBRARY_PATH': '/host/lib',
                'UNITY_SCALE_HOST_PATH': '/host/bin', 'UNITY_SCALE_HOST_XDG_DATA_DIRS': '/host/share'}):
            env = updates.host_environment()
            self.assertNotIn('APPDIR', env)
            self.assertNotIn('PYTHONHOME', env)
            self.assertEqual(env['LD_LIBRARY_PATH'], '/host/lib')
            self.assertEqual(env['PATH'], '/host/bin')
            self.assertEqual(env['XDG_DATA_DIRS'], '/host/share')

    def test_invalid_cli_scale_never_connects_an_editor(self):
        from unity_scale.__main__ import main
        store = SimpleNamespace(get_profile=lambda _path: dict(override_enabled=False, ui_scale_percent=150,
                    follow_desktop=False, render_scale=2, control_revision=1))
        with patch('unity_scale.core.Store', return_value=store), patch('unity_scale.core.inspect_editor',
                return_value=SimpleNamespace(path='/tmp/inert-editor', version='6000.3.27f2')), \
                patch('unity_scale.native_backend.ensure_connected') as connect, patch('sys.stderr', io.StringIO()):
            self.assertEqual(main(['configure', '--editor', '/tmp/inert-editor', '--scale', '300']), 1)
            connect.assert_not_called()


@unittest.skipUnless(shutil.which('cc') and shutil.which('openssl') and shutil.which('pkg-config'), 'native verifier toolchain unavailable')
class SignatureTests(unittest.TestCase):
    def test_apply_acknowledges_success_and_restores_on_failure(self):
        for success in (True, False):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                helper = base / 'helper'
                source = Path(__file__).resolve().parents[1] / 'packaging/update_helper.c'
                libs = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'openssl'], text=True).split()
                wrapper = base / 'signal-check.c'
                wrapper.write_text('#include <sys/types.h>\n#include <stdio.h>\n'
                    'int __real_kill(pid_t,int);\n'
                    'int __wrap_kill(pid_t p,int s){if(s)fprintf(stderr,"unexpected-signal:%d\\n",s);return __real_kill(p,s); }\n')
                subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(source), str(wrapper),
                                '-Wl,--wrap=kill', '-o', str(helper), *libs], check=True)
                stage = Path(tempfile.mkdtemp(prefix='.update-', dir=base))
                old = b'#!/bin/sh\nexit 0\n'
                new = b'#!/bin/sh\nprintf %s "$4" > "$3"\n' if success else b'#!/bin/sh\nexit 1\n'
                target = base / 'application.AppImage';target.write_bytes(old);target.chmod(0o700)
                image = stage / 'new.AppImage';image.write_bytes(new);image.chmod(0o700)
                private = base / 'private.pem';public = stage / 'public-key.pem'
                subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(private)], check=True, capture_output=True)
                subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)], check=True, capture_output=True)
                manifest = stage / 'release.json';signature = stage / 'release.json.sig'
                manifest.write_text(json.dumps(dict(schema=1, version='0.5.0', channel='stable', architecture='x86_64',
                    filename=updates.FILENAME, size=len(new), sha256=hashlib.sha256(new).hexdigest())))
                subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(private), '-in', str(manifest), '-out', str(signature)], check=True, capture_output=True)
                result = subprocess.run([str(helper), 'apply', '2147483647', str(target), str(image), str(manifest),
                    str(signature), str(public), str(stage / 'healthy'), 'a' * 64, '0.5.0'], timeout=10, check=False, capture_output=True)
                self.assertEqual(result.returncode, 0 if success else 1)
                self.assertEqual(result.stderr, b'', 'Never signal an exited/reaped update child')
                self.assertEqual(target.read_bytes(), new if success else old)
                self.assertFalse(target.with_name('application.AppImage.rollback').exists())
                self.assertFalse(stage.exists())

    def test_native_manifest_parser_rejects_duplicates_nul_and_wrong_version(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = Path(__file__).resolve().parents[1] / 'packaging/update_helper.c'
            harness = base / 'schema.c'
            harness.write_text('#define main helper_main\n#include "' + str(source) + '"\n#undef main\n'
                'int main(int n,char **v){long long size=0;char hash[65];if(n!=3)return 2;'
                'return schema((unsigned char*)v[1],strlen(v[1]),v[2],&size,hash)?0:1;}\n')
            libs = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'openssl'], text=True).split()
            tester = base / 'schema'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(harness), '-o', str(tester), *libs], check=True)
            _, values = fixture('0.5.0')
            manifest = values[BASE + 'v0.5.0/release.json'].decode()
            cases = [(manifest, '0.5.0', 0), (manifest, '0.6.0', 1),
                (manifest.replace('{', '{"schema":1,', 1), '0.5.0', 1),
                (manifest.replace('"0.5.0"', '"0.5.0\\u0000"'), '0.5.0', 1),
                (manifest.replace('"stable"', '"prerelease"'), '0.5.0', 1),
                (manifest + '{}', '0.5.0', 1),
                (manifest.replace('"schema": 1', '"schema": 01'), '0.5.0', 1)]
            for document, version, code in cases:
                with self.subTest(document=document, version=version):
                    self.assertEqual(subprocess.run([str(tester), document, version], check=False).returncode, code)

    def test_real_ed25519_valid_tamper_and_wrong_key(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            helper = base / 'helper'
            source = Path(__file__).resolve().parents[1] / 'packaging/update_helper.c'
            libs = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'openssl'], text=True).split()
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(helper), *libs], check=True)
            private = base / 'private.pem';public = base / 'public.pem'
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(private)], check=True, capture_output=True)
            subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)], check=True, capture_output=True)
            manifest = base / 'manifest';signature = base / 'signature'
            manifest.write_bytes(b'{"signed":"exact bytes"}\n')
            subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(private), '-in', str(manifest), '-out', str(signature)], check=True, capture_output=True)
            updates.verify_signature(manifest.read_bytes(), signature.read_bytes(), helper=helper, public_key=public)
            with self.assertRaises(updates.UpdateError):
                updates.verify_signature(manifest.read_bytes() + b' ', signature.read_bytes(), helper=helper, public_key=public)
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(private)], check=True, capture_output=True)
            subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)], check=True, capture_output=True)
            with self.assertRaises(updates.UpdateError):
                updates.verify_signature(manifest.read_bytes(), signature.read_bytes(), helper=helper, public_key=public)


if __name__ == '__main__':
    unittest.main()
