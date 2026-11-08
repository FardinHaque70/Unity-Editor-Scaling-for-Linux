"""Editor discovery and user-wide configuration. This module never starts Unity."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re

from . import __version__

APP_ID = "io.github.unityscale.UnityScale"
ICON_NAME = "io.github.unityscale.UnityScale"
APP_NAME = "Unity Editor Scaling for Linux"
APP_SLUG = "unity-editor-scaling-for-linux"
VERSION = __version__
REPOSITORY_URL = "https://github.com/FardinHaque70/Unity-Editor-Scaling-for-Linux"
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


from .private_store import Store


@dataclass(frozen=True)
class Editor:
    path: str
    version: str
    label: str
    source: str = "Located Editor"

    def to_dict(self) -> dict:
        return asdict(self)


_VERSION = re.compile(r"(?<!\d)(\d{4}\.\d+\.\d+[abfp]\d+)(?!\w)")
_LAB_MARKERS = (".scaling-lab-disposable", ".unity-scaling-lab")


def _read_text(path: Path, limit: int = 4096) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        return stream.read(limit)


def is_lab_editor(path: str | Path) -> bool:
    """Exclude this app's files and explicitly marked disposable directories."""
    target = Path(path).expanduser().resolve()
    if target.is_relative_to(ROOT.resolve()):
        return True
    return any((parent / marker).is_file()
               for parent in target.parents for marker in _LAB_MARKERS)


def _editor_version(target: Path) -> str:
    # Read installation metadata only. Never execute Unity --version, a shell
    # launcher, or a project merely to obtain the Editor's version.
    for file in (target.parent / "UnityVersion.txt",
                 target.parent.parent / "UnityVersion.txt",
                 target.parent / "Data/Resources/UnityVersion.txt"):
        try:
            match = _VERSION.search(_read_text(file))
            if match:
                return match[1]
        except OSError:
            pass
    for folder in (target.parent, target.parent.parent):
        match = _VERSION.fullmatch(folder.name)
        if match:
            return match[1]
    return "Unknown version"


def inspect_editor(path: str | Path) -> Editor:
    target = Path(path).expanduser()
    if target.is_dir():
        candidates = [target / "Editor/Unity", target / "Unity"]
        target = next((p for p in candidates if p.is_file()), target / "Editor/Unity")
    target = target.resolve()
    if is_lab_editor(target):
        raise AppError("Choose an installed Editor outside the app's disposable experiment folders.")
    if not target.is_file() or not os.access(target, os.X_OK):
        raise AppError("Select an executable Unity Editor, or its installation folder.")
    if target.name != "Unity":
        raise AppError("Choose the Editor executable named Unity, usually inside its Editor folder.")
    from .native_backend import is_owned_candidate, verified_original
    inspected = target
    if is_owned_candidate(target):
        try:
            inspected = verified_original(target)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AppError("The app-owned Editor launcher cannot be verified: " + str(exc)) from exc
    try:
        with inspected.open("rb") as stream:
            head = stream.read(64)
    except OSError as exc:
        raise AppError(f"Cannot read the Editor executable: {exc}") from exc
    # Only a fully verified owned launcher can stand in for the original ELF.
    valid_elf = (len(head) >= 52 and head.startswith(b"\x7fELF") and
                 head[4] in (1, 2) and head[5] in (1, 2) and head[6] == 1 and
                 (head[4] == 1 or len(head) >= 64) and
                 int.from_bytes(head[16:18], "little" if head[5] == 1 else "big") in (2, 3))
    if not valid_elf:
        raise AppError("Choose the installed Linux Unity Editor ELF executable; scaling launcher scripts are not supported.")
    data = target.parent / "Data"
    if not (data / "Managed/UnityEditor.dll").is_file() or not (data / "Resources").is_dir():
        raise AppError("This executable does not have a valid Unity Editor installation beside it. Select Unity inside the installed Editor folder.")
    version = _editor_version(target)
    label = f"Unity {version}" if version != "Unknown version" else "Unity Editor"
    return Editor(str(target), version, label)


def _hub_install_roots(config: Path) -> list[Path]:
    roots = []
    for folder in (config / "unityhub", config / "UnityHub"):
        for name in ("secondaryInstallPath.json", "user-settings.json", "settings.json"):
            file = folder / name
            try:
                data = json.loads(_read_text(file, 65536))
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


def discover_editors(extra_paths: list[str] | None = None, *, store=None, include_lab=False) -> list[Editor]:
    """Find distinct installed Editors; include_lab is legacy call compatibility.

    Explicitly marked/app-owned experiment copies are always excluded.
    """
    home = Path.home()
    config = _xdg("XDG_CONFIG_HOME", ".config")
    roots = [home / "Unity/Hub/Editor", Path("/opt/unity/Editor"), Path("/opt/Unity/Hub/Editor"), home / ".local/share/Unity/Hub/Editor"]
    roots += _hub_install_roots(config)
    paths = list(extra_paths or [])
    paths += (store if store is not None else Store()).load().get("extra_editors", [])
    roots = list(dict.fromkeys(root.resolve() for root in roots if root.is_absolute()))
    for root in roots:
        try:
            for pattern in ("*/Editor/Unity", "*/Unity", "Editor/Unity", "Unity"):
                paths.extend(root.glob(pattern))
        except OSError:
            continue
    found = {}
    for path in paths:
        try:
            editor = inspect_editor(path)
            if editor.path not in found:
                source = "Unity Hub" if any(Path(editor.path).is_relative_to(root) for root in roots) else "Located Editor"
                found[editor.path] = Editor(editor.path, editor.version, editor.label, source)
        except (AppError, OSError, TypeError):
            continue
    def version_key(editor):
        return tuple(int(p) for p in re.findall(r"\d+", editor.version))
    return sorted(found.values(), key=version_key, reverse=True)


def environment_status():
    return {"supported": False, "settings_manager_supported": True,
            "native_backend_available": None, "native_backend_verified": False,
            "summary": "Native startup integration is verified separately for each Editor; changes require restarting Unity.",
            "checks": [], "bridge_used": False, "bridge_present": None}


def diagnostics():
    """Privacy-limited report; does not probe a compositor or a bridge."""
    return {"application": APP_NAME, "version": VERSION,
            "backend": "Native startup integration requires verified per-Editor setup",
            "backend_selection": "per-editor-startup", "live_apply": False,
            "production_applied": False, "presented": False,
            "effective_scale_acknowledgement": False, "current_scale": None,
            "bridge_used": False, "bridge_present": None,
            "capabilities": {
                "settings_manager": {
                    "supported": True, "project_independent": True,
                    "profile_scope": "per-Editor app settings",
                    "custom_percent_range": [MIN_UI_SCALE, MAX_UI_SCALE],
                    "unity_default_choice": True, "saving_applies_scale": False},
                "native_startup": {"requires_verified_setup": True, "restart_required": True,
                    "supported_editor": "6000.3.27f2", "supported_elf_sha256":
                    "d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec",
                    "custom_scope": "KDE Wayland / X11 GTK / OpenGL", "default_is_stock": True,
                    "physical_input_verified": False, "performance_verified": False}},
            "environment": environment_status(),
            "system": {"platform": platform.system(), "architecture": platform.machine()},
            "project_paths_included": False, "raw_logs_included": False}


def get_running_scale(editor_path):
    return None  # Discovery alone does not establish a running scale.
