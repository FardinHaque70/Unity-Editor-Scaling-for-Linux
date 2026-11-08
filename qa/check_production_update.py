#!/usr/bin/env python3
"""Exercise signed public AppImage updates in private Broadway and a temp HOME.

Run only AFTER the accepted prerelease is public. The starting image is a copy
of that artifact with an inert trailer and a simulated previous prerelease
receipt, explicitly not a historical released application. The candidate,
signature, download transport, helper, replacement, GUI health ACK and rollback
are the actual shipped production paths. No Unity, daily files, desktop windows
or background service are involved. All temporary processes/files are removed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

QA = Path(__file__).resolve().parent

# Executed in a private bus after the worker hands off to the real updater.
CASE_CONTROLLER = '''import json,os,subprocess,sys,time
from pathlib import Path
worker=subprocess.run(sys.argv[1:],check=False)
if worker.returncode:raise SystemExit(worker.returncode)
record=json.loads(Path(os.environ['QA_UPDATE_RESULT']).read_text())
target=Path(record['target']);stage=Path(record['stage'])
receipt=Path(record['state_dir'])/'installation.json'
expected=record['expected_sha256'] if record['mode']=='success' else record['previous_sha256']
deadline=time.monotonic()+90
while time.monotonic()<deadline:
 if not stage.exists() and not target.with_name(target.name+'.rollback').exists():
  import hashlib
  if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==expected:
   if receipt.exists() and json.loads(receipt.read_text()).get('image_sha256')==expected:
    record.update(status='PASS', final_sha256=expected, rollback_removed=True, staging_removed=True)
    Path(os.environ['QA_UPDATE_RESULT']).write_text(json.dumps(record,indent=2)+'\\n')
    raise SystemExit(0)
 time.sleep(.1)
raise SystemExit('Update did not settle to expected image/receipt within90seconds')
'''


def stop_owned(marker):
    # Detached update helpers have their own process group. Match only the
    # unguessable marker inherited by this disposable exercise, never names.
    owned = []
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid == os.getuid() and ('UNITY_SCALE_QA_SESSION=' + marker).encode() in (process / 'environ').read_bytes().split(b'\0'):
                owned.append(int(process.name))
        except (OSError, ProcessLookupError):
            pass
    for signum in (signal.SIGTERM, signal.SIGKILL):
        for pid in owned:
            try:
                process = Path('/proc') / str(pid)
                if ('UNITY_SCALE_QA_SESSION=' + marker).encode() in (process / 'environ').read_bytes().split(b'\0'):
                    os.kill(pid, signum)
            except (OSError, ProcessLookupError):
                pass
        if signum == signal.SIGTERM:
            time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    image = args.image.resolve()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('Evidence output must be absent or empty')
    output.mkdir(parents=True, exist_ok=True)
    result = {'status': 'FAIL', 'daily_files_changed': False, 'Unity_launched': False,
              'desktop_windows': False, 'cases': []}
    marker = uuid.uuid4().hex
    processes, logs = [], []
    temporary = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix='unity-production-update-')
        root = Path(temporary.name)
        subprocess.run([str(image), '--appimage-extract'], cwd=root, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        appdir = root / 'squashfs-root'
        dbus = shutil.which('dbus-run-session')
        if not dbus:
            raise RuntimeError('dbus-run-session is needed for private widget QA')
        runtime = root / 'runtime';runtime.mkdir(mode=0o700)
        env = {k:v for k,v in os.environ.items() if k not in (
            'APPIMAGE','APPDIR','PYTHONHOME','PYTHONPATH','LD_LIBRARY_PATH','LD_PRELOAD',
            'GI_TYPELIB_PATH','GIO_MODULE_DIR','GIO_EXTRA_MODULES','GTK_DATA_PREFIX',
            'GSETTINGS_SCHEMA_DIR','GDK_PIXBUF_MODULEDIR','GDK_PIXBUF_MODULE_FILE',
            'DBUS_SESSION_BUS_ADDRESS','DISPLAY','WAYLAND_DISPLAY') and not k.startswith('UNITY_SCALE_')}
        env.update(APPDIR=str(appdir), QA_APP_ROOT=str(appdir / 'usr/share/unity-editor-scaling'),
                   QA_UPDATE_ROOT=str(root), QA_UPDATE_IMAGE=str(image),
                   UNITY_SCALE_QA_SESSION=marker, GDK_BACKEND='broadway', BROADWAY_DISPLAY=':8',
                   GSK_RENDERER='cairo', GSETTINGS_BACKEND='memory', GTK_A11Y='none',
                   XDG_RUNTIME_DIR=str(runtime), APPIMAGE_EXTRACT_AND_RUN='1',
                   PYTHONDONTWRITEBYTECODE='1')
        original = (appdir / 'AppRun').read_text()
        final = '"$APPDIR/usr/bin/python3.10" -S -c \'import sys; sys.path = [p for p in sys.path if p]; sys.argv[0] = "unity-scale"; from unity_scale.__main__ import main; raise SystemExit(main())\' "$@"'
        if original.count(final) != 1:
            raise RuntimeError('Unknown AppRun QA contract')
        python_wrapper = root / 'python-runtime.sh'
        python_wrapper.write_text(original.replace(final, '"$APPDIR/usr/bin/python3.10" -S "$@"'))
        python_wrapper.chmod(0o700)
        broadway_wrapper = root / 'broadway-runtime.sh'
        broadway_wrapper.write_text(original.replace(final, '"$APPDIR/usr/bin/gtk4-broadwayd" "$@"'))
        broadway_wrapper.chmod(0o700)
        bus_config = root / 'dbus.conf'
        bus_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=' + str(runtime) +
            '</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/>'
            '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')

        def start(command, name, environment):
            stream = (output / (name + '.log')).open('w');logs.append(stream)
            process = subprocess.Popen(list(map(str, command)), env=environment, cwd=root,
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(process)
            return process

        # The private bus must outlive the worker, helper and replacement
        # GUI. dbus-run-session owns the whole case controller, not worker.
        controller = root / 'case-controller.py'
        controller.write_text(CASE_CONTROLLER)
        server = start([broadway_wrapper, '-u', root / 'http.socket', ':8'], 'broadway', env)
        deadline = time.monotonic() + 10
        while not (root / 'http.socket').exists():
            if server.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Private Broadway startup failed')
            time.sleep(0.05)
        for mode in ('success', 'rollback'):
            home = root / (mode + '-home');home.mkdir(mode=0o700)
            case_env = dict(env, HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'),
                XDG_DATA_HOME=str(home / 'data'), XDG_STATE_HOME=str(home / 'state'),
                XDG_CACHE_HOME=str(home / 'cache'), QA_UPDATE_MODE=mode,
                QA_UPDATE_RESULT=str(output / (mode + '.json')))
            process = start([dbus, '--config-file=' + str(bus_config), '--', python_wrapper,
                controller, python_wrapper, QA / 'update_artifact_worker.py'], mode, case_env)
            code = process.wait(timeout=180)
            record_path = output / (mode + '.json')
            record = json.loads(record_path.read_text()) if record_path.exists() else {'status':'FAIL'}
            result['cases'].append(record)
            if code or record['status'] != 'PASS':
                raise RuntimeError('Production ' + mode + ' exercise failed; see case log')
            # End only tagged processes from the completed case. Broadway
            # is needed again, so individual case controllers terminate GUI
            # when their private bus disappears; remaining tagged children
            # are removed at final cleanup.
        result['status'] = 'PASS'
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        stop_owned(marker)
        for process in reversed(processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=3)
        for stream in logs:stream.close()
        if temporary is not None:
            temporary.cleanup()
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
