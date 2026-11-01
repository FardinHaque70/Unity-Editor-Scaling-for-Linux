"""Editor discovery and user-wide configuration. This module never starts Unity."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import ctypes
import ctypes.util
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

from . import __version__

APP_ID = "io.github.unityscale.UnityScale"
APP_NAME = "Unity Editor UI Scalar for Linux"
APP_SLUG = "unity-editor-ui-scalar-for-linux"
VERSION = __version__
REPOSITORY_URL = "https://github.com/FardinHaque70/unity-editor-ui-scalar-for-linux"
MIN_UI_SCALE = 100
MAX_UI_SCALE = 200
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = {"ui_scale_percent": 150, "follow_desktop": False, "render_scale": 2}


class AppError(Exception):
    """An actionable error safe to show in the application."""


def _xdg(env_name: str, fallback: str) -> Path:
    value = os.environ.get(env_name)
    # XDG specifies absolute paths; ignore relative environment values.
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def editor_key(path: str | Path) -> str:
    return hashlib.sha256(str(Path(path).expanduser().resolve()).encode()).hexdigest()[:24]


def validate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict):
        raise AppError("The saved Editor settings are invalid.")
    result = dict(DEFAULT_PROFILE)
    result.update({key: value for key, value in profile.items() if key in {
        *DEFAULT_PROFILE, "desktop_scale_percent", "cursor_theme", "cursor_size"}})
    scale = result["ui_scale_percent"]
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not MIN_UI_SCALE <= scale <= MAX_UI_SCALE or scale != int(scale):
        raise AppError(f"Choose a whole Editor scale between {MIN_UI_SCALE}% and {MAX_UI_SCALE}%.")
    result["ui_scale_percent"] = int(scale)
    if not isinstance(result["follow_desktop"], bool):
        raise AppError("Follow desktop must be true or false.")
    density = result["render_scale"]
    if isinstance(density, bool) or not isinstance(density, int) or density not in (1, 2, 3, 4):
        raise AppError("Rendering density must be an integer between 1 and 4.")
    reference = result.get("desktop_scale_percent")
    if reference is not None and (isinstance(reference, bool) or not isinstance(reference, (int,float)) or not math.isfinite(reference) or not 50 <= reference <= 500):
        raise AppError("The desktop scale reference must be between50% and500%.")
    cursor = result.get("cursor_size")
    if cursor is not None and (isinstance(cursor, bool) or not isinstance(cursor, int) or not 1 <= cursor <= 128):
        raise AppError("Cursor size must be an integer between1 and128.")
    theme = result.get("cursor_theme")
    if theme is not None and (not isinstance(theme, str) or not theme or any(c in theme for c in "\r\n\0")):
        raise AppError("Invalid cursor theme.")
    return result


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".settings-", delete=False, encoding="utf-8") as stream:
            name = stream.name
            os.chmod(name, 0o600)
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


class Store:
    def __init__(self):
        self.config_dir = _xdg("XDG_CONFIG_HOME", ".config") / "unity-scale"
        self.state_dir = _xdg("XDG_STATE_HOME", ".local/state") / "unity-scale"
        self.data_dir = _xdg("XDG_DATA_HOME", ".local/share") / "unity-scale"
        self.path = self.config_dir / "settings.json"

    def load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "editors": {}, "extra_editors": []}
        try:
            value = json.loads(self.path.read_text())
            if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("editors"), dict) or not isinstance(value.get("extra_editors", []), list) or any(not isinstance(item, str) for item in value.get("extra_editors", [])) or any(not isinstance(key, str) or not isinstance(profile, dict) for key, profile in value.get("editors", {}).items()):
                raise ValueError("unrecognized settings format")
            return value
        except (OSError, ValueError, TypeError) as exc:
            raise AppError(f"Could not read settings at {self.path}: {exc}. The file was left untouched.") from exc

    def save(self, settings: dict) -> None:
        if not isinstance(settings, dict) or settings.get("schema_version") != 1 or not isinstance(settings.get("editors"), dict):
            raise AppError("Cannot save invalid application settings.")
        _atomic_json(self.path, settings)

    def get_profile(self, editor_path: str | Path) -> dict:
        key = str(Path(editor_path).expanduser().resolve())
        entry = self.load()["editors"].get(key, {})
        return validate_profile(entry)

    def set_profile(self, editor_path: str | Path, profile: dict) -> None:
        validated = validate_profile(profile)
        settings = self.load()
        settings["editors"][str(Path(editor_path).expanduser().resolve())] = validated
        self.save(settings)

    def add_editor(self, path: str | Path) -> Editor:
        editor = inspect_editor(str(path))
        settings = self.load()
        settings.setdefault("extra_editors", [])
        if editor.path not in settings["extra_editors"]:
            settings["extra_editors"].append(editor.path)
        self.save(settings)
        return editor

    def remove_editor(self, path: str | Path) -> None:
        identity = str(Path(path).expanduser().resolve())
        settings = self.load()
        settings["extra_editors"] = [p for p in settings.get("extra_editors", []) if p != identity]
        self.save(settings)


@dataclass(frozen=True)
class Editor:
    path: str
    version: str
    label: str
    source: str = "Located Editor"

    def to_dict(self) -> dict:
        return asdict(self)


_VERSION = re.compile(r"(?<!\d)(\d{4}\.\d+\.\d+[abfp]\d+)(?!\w)")


def inspect_editor(path: str | Path) -> Editor:
    target = Path(path).expanduser()
    if target.is_dir():
        candidates = [target / "Editor/Unity", target / "Unity"]
        target = next((p for p in candidates if p.is_file()), target / "Editor/Unity")
    target = target.resolve()
    if not target.is_file() or not os.access(target, os.X_OK):
        raise AppError("Select an executable Unity Editor, or its installation folder.")
    if target.name != "Unity":
        raise AppError("Choose the Editor executable named Unity, usually inside its Editor folder.")
    try:
        with target.open("rb") as stream:
            head = stream.read(512)
    except OSError as exc:
        raise AppError(f"Cannot read the Editor executable: {exc}") from exc
    # No code execution for discovery, including scripts supplied through Locate.
    if not (head.startswith(b"\x7fELF") or b"UNITY_SCALE_MANAGED_WRAPPER" in head or b"unity-scale managed" in head.lower()):
        raise AppError("This is not a Linux Unity Editor executable or a managed scaling launcher.")
    data = target.parent / "Data"
    if not (data / "Managed/UnityEditor.dll").is_file() or not (data / "Resources").is_dir():
        raise AppError("This executable does not have a valid Unity Editor installation beside it. Select Unity inside the installed Editor folder.")
    match = _VERSION.search(str(target.parent.parent))
    version = match[1] if match else "Unknown version"
    if version == "Unknown version":
        for file in (target.parent / "UnityVersion.txt", target.parent.parent / "UnityVersion.txt"):
            try:
                match = _VERSION.search(file.read_text()[:4096])
                if match:version = match[1];break
            except OSError:
                pass
    label = f"Unity {version}" if version != "Unknown version" else "Unity Editor"
    return Editor(str(target), version, label)


def _hub_install_roots(config: Path) -> list[Path]:
    roots = []
    for folder in (config / "unityhub", config / "UnityHub"):
        for name in ("secondaryInstallPath.json", "user-settings.json", "settings.json"):
            file = folder / name
            try:
                data = json.loads(file.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, str):
                roots.append(Path(data).expanduser())
            elif isinstance(data, dict):
                for key in ("secondaryInstallPath", "installPath", "installLocation", "editorInstallPath"):
                    value = data.get(key)
                    if isinstance(value, str) and value:
                        roots.append(Path(value).expanduser())
    return roots


def discover_editors(extra_paths: list[str] | None = None) -> list[Editor]:
    home = Path.home()
    config = _xdg("XDG_CONFIG_HOME", ".config")
    roots = [home / "Unity/Hub/Editor", Path("/opt/unity/Editor"), Path("/opt/Unity/Hub/Editor"), home / ".local/share/Unity/Hub/Editor"]
    roots += _hub_install_roots(config)
    paths = list(extra_paths or [])
    paths += Store().load().get("extra_editors", [])
    for root in roots:
        if not root.is_absolute():continue
        for pattern in ("*/Editor/Unity", "*/Unity", "Editor/Unity", "Unity"):
            paths += [str(p) for p in root.glob(pattern)]
    found = {}
    for path in paths:
        try:
            editor = inspect_editor(path)
            if editor.path not in found:
                found[editor.path] = Editor(editor.path, editor.version, editor.label, "Unity Hub" if any(str(root) in editor.path for root in roots) else "Located Editor")
        except (AppError, OSError, TypeError):
            continue
    def version_key(editor):
        return tuple(int(p) for p in re.findall(r"\d+", editor.version))
    return sorted(found.values(), key=version_key, reverse=True)


def helper_path() -> Path:
    override = os.environ.get("UNITY_SCALE_HELPER")
    return Path(override).expanduser().resolve() if override else ROOT / "libexec/xwayland-satellite"


def desktop_scale() -> float | None:
    if shutil.which("kscreen-doctor"):
        try:
            env = os.environ.copy()
            if env.get("UNITY_HOST_DISPLAY"):env["DISPLAY"] = env["UNITY_HOST_DISPLAY"]
            data = json.loads(subprocess.check_output(["kscreen-doctor", "-j"], text=True, stderr=subprocess.DEVNULL, timeout=4, env=env))
            outputs = [o for o in data.get("outputs", []) if o.get("connected") and o.get("enabled")]
            if outputs:
                primary = min(outputs, key=lambda o: o.get("priority") or 999)
                result = float(primary["scale"]) * 100
                if math.isfinite(result) and 50 <= result <= 500:return result
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
    value = os.environ.get("UNITY_DESKTOP_SCALE_PERCENT")
    if value:
        try:
            result = float(value)
            if math.isfinite(result) and 50 <= result <= 500:return result
        except ValueError:
            pass
    return None


def environment_status() -> dict:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "Unknown")
    session = os.environ.get("XDG_SESSION_TYPE", "wayland" if os.environ.get("WAYLAND_DISPLAY") else "unknown")
    checks = []
    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    check("KDE Wayland", "kde" in desktop.lower() and bool(os.environ.get("WAYLAND_DISPLAY")) and session.lower() == "wayland", f"{desktop} · {session}")
    check("Architecture", platform.machine() == "x86_64", platform.machine())
    check("Xwayland", shutil.which("Xwayland"), "Installed" if shutil.which("Xwayland") else "Install Xwayland with your distribution package manager")
    helper = helper_path()
    check("Scaling bridge", helper.is_file() and os.access(helper, os.X_OK), "Installed" if helper.is_file() else "Build or install the bundled bridge")
    check("X11 library", ctypes.util.find_library("X11"), "Available" if ctypes.util.find_library("X11") else "Install libX11")
    # ldd inspects our own package helper, never any located user Editor executable.
    if helper.is_file():
        try:
            loader = subprocess.run(["ldd", str(helper)], capture_output=True, text=True, timeout=5)
            missing = [line.strip() for line in (loader.stdout+loader.stderr).splitlines() if "not found" in line]
            check("Bridge libraries", loader.returncode == 0 and not missing, "; ".join(missing) or ("Available" if loader.returncode == 0 else "Cannot inspect bridge libraries"))
        except (OSError, subprocess.SubprocessError):
            check("Bridge libraries", False, "Install ldd to verify bridge libraries")
    protocols = None
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wayland-info"):
        try:
            probe = subprocess.run(["wayland-info"], capture_output=True, text=True, timeout=6)
            required = ("xdg_wm_base", "wp_viewporter", "zxdg_output_manager_v1")
            missing = [name for name in required if f"'{name}'" not in probe.stdout]
            protocols = probe.returncode == 0 and not missing
            check("Wayland protocols", protocols, "Available" if protocols else "Missing: " + ", ".join(missing))
        except (OSError, subprocess.SubprocessError):
            protocols = False
            check("Wayland protocols", False, "Could not inspect compositor protocols")
    scale = desktop_scale()
    check("Desktop scale", scale is not None, f"{scale:g}%" if scale else "Could not detect primary display scale")
    supported = all(c["ok"] for c in checks)
    return {"supported": supported, "desktop": desktop, "session": session, "desktop_scale_percent": scale,
            "checks": checks, "summary": "Ready for KDE Wayland beta" if supported else "Review compatibility checks before launching"}


def launch_command(editor_path: str, project: str | None = None, extra_args: list[str] | None = None) -> list[str]:
    command = [sys.executable, str(ROOT / "bin/unity-scale"), "run", "--editor", str(Path(editor_path).expanduser().resolve())]
    if project:command += ["--project", str(Path(project).expanduser().resolve())]
    if extra_args:command += ["--", *extra_args]
    return command


def diagnostics() -> dict:
    """Shareable report omitting project/Editor/home paths and raw Editor logs."""
    status = environment_status()
    # Dependency errors can contain install/home paths; scrub those before export.
    home = str(Path.home())
    for entry in status["checks"]:
        entry["detail"] = entry["detail"].replace(home, "~")
    return {"application": APP_NAME, "version": VERSION, "system": {"platform": platform.system(), "architecture": platform.machine(), "libc": platform.libc_ver()}, "environment": status, "bridge_revision": "prototype-v5.2", "project_paths_included": False, "raw_logs_included": False}


def get_running_scale(editor_path: str | Path) -> float | None:
    """Read the scale of a live supervised Editor, without exposing its arguments.

    A process must belong to this user and still use the recorded private display.
    This also follows replacement Editor PIDs recorded during native relaunch.
    """
    identity = str(Path(editor_path).expanduser().resolve())
    runs = Store().state_dir / "runs"
    for file in sorted(runs.glob("*/launch.json"), reverse=True)[:100]:
        try:
            if file.stat().st_size > 128 * 1024:continue
            value = json.loads(file.read_text())
            if value.get("editor") != identity or value.get("status") in ("exited", "failed"):
                continue
            pids = [value.get("editor_pid"), *value.get("handoff_editor_pids", []), *value.get("handoff_seen_pids", [])]
            for pid in pids:
                if not isinstance(pid, int) or pid <= 0:continue
                proc = Path("/proc") / str(pid)
                try:
                    if proc.stat().st_uid != os.getuid():continue
                    fields = (proc / "stat").read_text().rpartition(")")[2].split()
                    if not fields or fields[0] == "Z":continue
                    env = dict(part.split(b"=", 1) for part in (proc / "environ").read_bytes().split(b"\0") if b"=" in part)
                    if env.get(b"DISPLAY", b"").decode(errors="replace") != value.get("display"):
                        continue
                    if env.get(b"UNITY_SCALE_ACTIVE") != b"1":continue
                    result = float(env.get(b"UNITY_EDITOR_UI_SCALE_PERCENT", b"nan"))
                    if math.isfinite(result) and 50 <= result <= 500:return result
                except (OSError, ValueError):
                    continue
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return None
