#!/usr/bin/python3
"""Bounded actual-widget checks on private Broadway, without desktop windows.

Uses system PyGObject, GTK4 Broadway, dbus-run-session and native Cairo snapshots.
No browser, Unity, download, installed settings or persistent service is involved.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

APP = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=APP / "qa/output")
    args = parser.parse_args()
    broadway = shutil.which("gtk4-broadwayd")
    dbus = shutil.which("dbus-run-session")
    if not broadway or not dbus:
        parser.error("gtk4-broadwayd and dbus-run-session are required")
    output = args.output.absolute()
    if output.exists() and any(output.iterdir()):
        parser.error("Output directory must be absent or empty; preserve previous evidence")
    output.mkdir(parents=True, exist_ok=True)
    processes, logs = [], []
    temporary_dir = None
    result = {"scope": "Actual GTK widgets on Broadway; software interactions and native Cairo snapshots",
              "status": "FAIL", "desktop_windows": False, "unity_launched": False}
    try:
        temporary_dir = tempfile.TemporaryDirectory(prefix="unity-scale-gtk-qa-")
        temporary = temporary_dir.name
        root = Path(temporary)
        for name in ("home", "config", "cache", "data", "state", "runtime"):
            (root / name).mkdir(mode=0o700)
        bus_config = root / "dbus.conf"
        bus_config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=' +
                              str(root / "runtime") + '</listen><auth>EXTERNAL</auth>'
                              '<policy context="default"><allow send_destination="*"/>'
                              '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
        env = os.environ.copy()
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "LD_PRELOAD", "PYTHONPATH",
                    "UNITY_SCALING_PRIVATE_V4", "GTK_MODULES", "GTK3_MODULES", "GTK_THEME"):
            env.pop(key, None)
        env.update(HOME=str(root / "home"), XDG_CONFIG_HOME=str(root / "config"),
                   XDG_CACHE_HOME=str(root / "cache"), XDG_DATA_HOME=str(root / "data"),
                   XDG_STATE_HOME=str(root / "state"), XDG_RUNTIME_DIR=str(root / "runtime"),
                   GDK_BACKEND="broadway", BROADWAY_DISPLAY=":7", GSK_RENDERER="cairo",
                   GSETTINGS_BACKEND="memory", GTK_A11Y="none", PYTHONDONTWRITEBYTECODE="1",
                   QA_STORE=str(root / "store"), QA_OUTPUT=str(output))

        def start(command, name):
            stream = (output / f"{name}.log").open("w")
            logs.append(stream)
            process = subprocess.Popen(command, env=env, cwd=APP, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            processes.append(process)
            return process

        # A private HTTP Unix socket avoids a public/network listener entirely.
        server = start([broadway, "-u", str(root / "http.socket"), ":7"], "broadway")
        deadline = time.monotonic() + 5
        while not (root / "http.socket").exists():
            if server.poll() is not None:
                raise RuntimeError("Broadway exited; see broadway.log")
            if time.monotonic() > deadline:
                raise TimeoutError("Private Broadway startup timed out")
            time.sleep(0.03)
        check = start([dbus, "--config-file=" + str(bus_config), "--", "/usr/bin/python3", str(APP / "qa/check_gtk.py")], "gtk-checks")
        result["gtk_exit_code"] = check.wait(timeout=75)
        if result["gtk_exit_code"]:
            raise RuntimeError("Actual GTK check failed; see gtk-checks.log and widgets.json")
        unit = start(["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests", "-v"], "unit-tests")
        result["unit_exit_code"] = unit.wait(timeout=30)
        if result["unit_exit_code"]:
            raise RuntimeError("Unit checks failed; see unit-tests.log")
        result["status"] = "PASS"
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        # Terminate only groups created here, including the isolated session bus.
        for process in reversed(processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in reversed(processes):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
        for stream in logs:
            stream.close()
        if temporary_dir is not None:
            temporary_dir.cleanup()
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
