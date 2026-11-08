"""Locked, atomic per-user profiles, independent of the application image."""
from contextlib import contextmanager
import copy
import fcntl
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "sandbox"
APP_DIR = "unity-editor-scaling-for-linux"


def xdg_path(name, fallback):
    value = os.environ.get(name)
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def error(message):
    from .core import AppError
    raise AppError(message)


def safe_root(root):
    root = Path(root).absolute()
    for part in (root, *root.parents):
        if part.is_symlink():
            error("Private data paths cannot contain symlinks.")
    return root


def atomic_json(path, value):
    if path.is_symlink() or path.parent.resolve() != path.parent:
        error("Refusing a symlink settings or journal file.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            name = stream.name
            os.chmod(name, 0o600)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def profile(value, *, require_revision=True):
    from .core import validate_profile
    if not isinstance(value, dict):
        error("Invalid profile.")
    result = dict(value)
    result.update(validate_profile(value))
    if result["follow_desktop"] is not False:
        error("Legacy Follow desktop requires an explicit default/custom migration choice.")
    if type(result.get("override_enabled")) is not bool:
        error("Profile needs an explicit override mode.")
    revision = result.get("control_revision")
    if require_revision and (type(revision) is not int or not 1 <= revision < 2**53):
        error("Invalid profile revision.")
    return result


class Store:
    def __init__(self, root=None):
        self.root = safe_root(root) if root is not None else safe_root(xdg_path("XDG_DATA_HOME", ".local/share") / APP_DIR)
        if root is not None:
            # An explicit root is a complete isolated test/profile environment.
            self.config_dir = self.root / "config/unity-scale"
            self.state_dir = self.root / "state/unity-scale"
            self.data_dir = self.root / "data/unity-scale"
        else:
            self.config_dir = safe_root(xdg_path("XDG_CONFIG_HOME", ".config") / APP_DIR)
            self.state_dir = safe_root(xdg_path("XDG_STATE_HOME", ".local/state") / APP_DIR)
            self.data_dir = self.root
        self.path = self.config_dir / "settings.json"

    @contextmanager
    def locked(self):
        safe_root(self.root)
        for path in (self.config_dir, self.state_dir, self.data_dir):
            if path.is_symlink() or path.resolve() != path:
                error("Unsafe private data directory.")
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor = os.open(self.config_dir / ".settings.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def load(self, *, legacy=False):
        safe_root(self.root)
        if self.path.is_symlink() or self.path.parent.resolve() != self.path.parent:
            error("Unsafe private settings path.")
        if not self.path.exists():
            return {"schema_version": 2, "editors": {}, "extra_editors": []}
        if self.path.stat().st_size > 1024 * 1024:
            error("Private settings file exceeds 1 MiB.")
        try:
            value = json.loads(self.path.read_text())
        except (ValueError, OSError) as exc:
            error(f"Cannot read private settings; file left untouched: {exc}")
        versions = (1, 2) if legacy else (2,)
        if (not isinstance(value, dict) or type(value.get("schema_version")) is not int or
                value["schema_version"] not in versions or not isinstance(value.get("editors"), dict) or
                not isinstance(value.get("extra_editors", []), list) or
                any(not isinstance(p, str) for p in value.get("extra_editors", []))):
            error("Settings need schema 2; use the application installer to migrate legacy profiles.")
        for key, entry in value["editors"].items():
            if not isinstance(key, str) or not Path(key).is_absolute() or not isinstance(entry, dict):
                error("Invalid Editor map.")
            if value["schema_version"] == 2:
                profile(entry)
        return value

    def get_profile(self, editor_path):
        key = str(Path(editor_path).expanduser().resolve())
        entry = self.load()["editors"].get(key, {})
        return profile(dict({"ui_scale_percent": 150, "follow_desktop": False, "render_scale": 2,
                             "override_enabled": False, "control_revision": 1}, **entry))

    def set_profile(self, editor_path, choice):
        return self.set_profile_change(editor_path, choice)[1]

    def set_profile_change(self, editor_path, choice):
        """Return the actual before/after choice from the same locked write."""
        key = str(Path(editor_path).expanduser().resolve())
        # Only this app's visible choice is changed; re-read preserves newer fields.
        checked = profile(dict(choice, control_revision=1))
        with self.locked():
            document = self.load()
            old = self.get_profile(key)
            changed = dict(old, ui_scale_percent=checked["ui_scale_percent"],
                           override_enabled=checked["override_enabled"], follow_desktop=False)
            if changed != old:
                changed["control_revision"] += 1
            document["editors"][key] = profile(changed)
            atomic_json(self.path, document)
        return old, changed

    def add_editor(self, path):
        from .core import inspect_editor
        editor = inspect_editor(path)
        with self.locked():
            value = self.load()
            if editor.path not in value.setdefault("extra_editors", []):
                value["extra_editors"].append(editor.path)
            atomic_json(self.path, value)
        return editor

    def remove_editor(self, path):
        key = str(Path(path).resolve())
        with self.locked():
            value = self.load()
            value["extra_editors"] = [p for p in value.get("extra_editors", []) if p != key]
            atomic_json(self.path, value)

    def migrate_legacy_copy(self, enabled):
        """Migrate ONLY this private store, requiring inspected mode per Editor."""
        with self.locked():
            value = self.load(legacy=True)
            if value["schema_version"] == 2:
                return value
            changed = copy.deepcopy(value)
            for editor, entry in changed["editors"].items():
                if type(enabled.get(editor)) is not bool:
                    error("Supply verified legacy override state for every Editor; never guess.")
                entry.update(override_enabled=enabled[editor], control_revision=1)
                changed["editors"][editor] = profile(entry)
            changed["schema_version"] = 2
            backup = self.path.with_suffix(".v1-backup.json")
            if backup.exists():
                error("Migration backup already exists; inspect it before retrying.")
            atomic_json(backup, value)
            atomic_json(self.path, changed)
            return changed
