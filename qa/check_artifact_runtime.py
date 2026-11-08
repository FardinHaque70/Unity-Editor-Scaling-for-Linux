#!/usr/bin/env python3
"""Run a release AppImage in a disposable HOME; never execute Unity fixtures.

Run this same script in clean Ubuntu/Fedora containers with only base runtime
packages. Normal mounting is mandatory when --require-normal is supplied;
extract-and-run and extracted AppRun are always mandatory. This test uses no
compiler, host GTK/Python modules or network.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--require-normal', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    image = args.image.resolve()
    image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    result = {'status': 'FAIL', 'image_sha256': image_hash, 'checks': [],
              'scope': 'Shipped runtime, relocation, inert Editor discovery and settings only; no Unity launch'}
    try:
        with tempfile.TemporaryDirectory(prefix='unity-artifact-runtime-') as tmp:
            root = Path(tmp)
            home = root / 'home'
            home.mkdir()
            env = {k: v for k, v in os.environ.items() if k not in (
                'APPIMAGE', 'APPDIR', 'PYTHONHOME', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD',
                'GI_TYPELIB_PATH', 'GIO_MODULE_DIR', 'GIO_EXTRA_MODULES', 'GTK_DATA_PREFIX',
                'GSETTINGS_SCHEMA_DIR', 'GDK_PIXBUF_MODULEDIR', 'GDK_PIXBUF_MODULE_FILE',
                'DBUS_SESSION_BUS_ADDRESS', 'DISPLAY', 'WAYLAND_DISPLAY') and not k.startswith('UNITY_SCALE_')}
            env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                       XDG_DATA_HOME=str(home / 'data'), XDG_CACHE_HOME=str(home / 'cache'),
                       XDG_STATE_HOME=str(home / 'state'), PYTHONDONTWRITEBYTECODE='1')
            moved = root / 'AppImage path with spaces' / image.name
            moved.parent.mkdir()
            shutil.copyfile(image, moved)
            moved.chmod(0o700)

            def run(argv, *, expected=0, cwd=root):
                command = subprocess.run(list(map(str, argv)), env=env, cwd=cwd, capture_output=True,
                                         text=True, timeout=60, check=False)
                if command.returncode != expected:
                    raise AssertionError('Artifact command failed: ' + repr([str(v) for v in argv[1:]]) +
                                         '\n' + command.stdout[-2000:] + command.stderr[-2000:])
                return command

            def json_output(command):
                return json.loads(command.stdout)

            if args.require_normal:
                normal = json_output(run([moved, '--self-test']))
                assert normal['healthy'] and normal['svg'] and normal['signed_verifier']
                result['checks'].append('normal Type-2 execution')
            else:
                result['normal_mount'] = 'not required in this environment; use --require-normal on FUSE host'
            report = json_output(run([moved, '--appimage-extract-and-run', '--self-test']))
            assert report['healthy'] and report['svg'] and report['cairo'] and report['signed_verifier']
            assert report['display_opened'] is False and report['installation_changed'] is False
            result['runtime'] = report
            result['checks'].append('extract-and-run with spaced/relocated path and no display')
            assert not any(home.iterdir()), 'Self-test wrote user configuration or installed itself'
            run([moved, '--appimage-extract'])
            apprun = root / 'squashfs-root/AppRun'
            assert json_output(run([apprun, '--self-test']))['healthy']
            result['checks'].append('extracted AppRun without AppImage mount')
            # Syntactically discoverable but deliberately unsupported, inert ELF.
            # Neither configure nor discovery is allowed to execute this file.
            editor = home / 'Unity installations/6000.3.27f2/Editor/Unity'
            editor.parent.mkdir(parents=True)
            head = bytearray(64)
            head[:7] = b'\x7fELF\x02\x01\x01';head[16:18] = (3).to_bytes(2, 'little')
            editor.write_bytes(head);editor.chmod(0o700)
            managed = editor.parent / 'Data/Managed';managed.mkdir(parents=True)
            (editor.parent / 'Data/Resources').mkdir()
            (managed / 'UnityEditor.dll').write_bytes(b'inert fixture; never execute')
            before = json_output(run([moved, '--appimage-extract-and-run', 'status', '--editor', editor]))
            assert before['version'] == '6000.3.27f2'
            assert before['native_backend_available'] is False
            saved = json_output(run([moved, '--appimage-extract-and-run', 'configure', '--editor', editor, '--unity-default']))
            assert saved['saved']['override_enabled'] is False
            settings = home / 'config/unity-editor-scaling-for-linux/settings.json'
            snapshot = settings.read_bytes()
            invalid = run([moved, '--appimage-extract-and-run', 'configure', '--editor', editor, '--scale', '300'], expected=1)
            assert 'between' in invalid.stderr
            unsupported = run([moved, '--appimage-extract-and-run', 'configure', '--editor', editor, '--scale', '150'], expected=1)
            assert unsupported.stderr
            assert settings.read_bytes() == snapshot
            assert editor.read_bytes() == head
            assert not (editor.parent / '.unity-editor-scaling').exists()
            restored = json_output(run([apprun, 'status', '--editor', editor]))
            assert restored['saved'] == saved['saved']
            result['checks'].append('unsupported Editor discovery, Default persistence and atomic custom refusal')
            assert hashlib.sha256(moved.read_bytes()).hexdigest() == image_hash
            result['checks'].append('AppImage unchanged after execution')
            result['status'] = 'PASS'
    except Exception as exc:
        result['error'] = str(exc)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
