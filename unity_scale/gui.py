"""Native, Editor-centric GTK interface for Unity Scale.

Discovery, integration, and environment checks run outside the GTK main loop.
The smoke test constructs the complete window using in-memory fixtures, without
presenting a window or touching an Editor, project, or settings file.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import core  # noqa: E402
from .gui_state import EditorEditState  # noqa: E402


def editor_paths(config: dict) -> list[str]:
    """Read saved locations while accepting older path-only configurations."""
    result = []
    for item in [*config.get("editors", []), *config.get("extra_editors", [])]:
        path = item.get("path") if isinstance(item, dict) else item
        if isinstance(path, str) and path and path not in result:
            result.append(path)
    return result


def edited_profile(existing: dict, percent: float, follow_desktop: bool) -> dict:
    """Keep advanced profile fields when changing the two visible controls."""
    profile = dict(existing)
    profile.update(ui_scale_percent=int(round(percent)), follow_desktop=bool(follow_desktop))
    profile.setdefault("render_scale", 2)
    return profile


def integration_action(status: dict) -> str:
    """Allow reversible recovery when an interrupted enable can be restored."""
    return "disable" if status.get("enabled") or status.get("can_disable") else "enable"


def diagnostic_text(editor, profile: dict) -> str:
    """Export the core privacy-limited report with only safe Editor fields."""
    report = core.diagnostics()
    report["editor_version"] = editor.version if editor else None
    report["profile"] = {key: profile[key] for key in
                         ("ui_scale_percent", "follow_desktop", "render_scale") if key in profile}
    return json.dumps(report, indent=2, ensure_ascii=False)


def start_editor(store, editor_path: str, profile: dict, project=None) -> Path:
    """Validate first, detach, and report a short-lived runner's startup error."""
    from . import runner
    store.set_profile(editor_path, profile)
    plan = runner.launch_plan(editor_path, project=project)
    status = plan.get("environment_status", {})
    if plan.get("mode") != "direct" and not status.get("supported", False):
        raise core.AppError(status.get("summary", "Review the desktop checks before launching."))
    state_dir = Path(store.state_dir)
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_path = state_dir / "gui-launch.log"
    with log_path.open("w", encoding="utf-8") as log:
        log_path.chmod(0o600)
        process = subprocess.Popen(core.launch_command(editor_path, project=project),
                                   start_new_session=True, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            return log_path
    if code:
        detail = log_path.read_text(errors="replace")[-1600:].strip()
        raise core.AppError(f"Unity could not start (exit {code}).\n\n{detail}\n\nStartup log: {log_path}")
    return log_path


def editor_title(editor) -> str:
    version = editor.version
    names = {"6000.3": "Unity 6.3 LTS", "6000.0": "Unity 6 LTS",
             "2022.3": "Unity 2022.3 LTS", "2021.3": "Unity 2021.3 LTS"}
    series = ".".join(version.split(".")[:2])
    name = names.get(series, "Unity Editor")
    return f"{name} ({version})"


def known_editors(store) -> list:
    """Read only saved locations. Discovery is an explicit user action."""
    found = []
    for path in editor_paths(store.load()):
        try:
            found.append(core.inspect_editor(path))
        except (core.AppError, OSError):
            continue
    return found


def apply_editor_override(store, editor_path: str, profile: dict, override: bool) -> dict:
    """Commit a staged choice; desktop checks never prevent restoring Unity."""
    from . import integration
    if not override:
        return integration.disable(editor_path)
    status = core.environment_status()
    if not status.get("supported"):
        failed = [entry.get("detail", entry.get("name", ""))
                  for entry in status.get("checks", []) if not entry.get("ok")]
        raise core.AppError(status.get("summary", "This desktop is not supported.") +
                            ("\n\n" + "\n".join(failed) if failed else ""))
    store.set_profile(editor_path, profile)
    return integration.enable(editor_path)


class _MemoryStore:
    def __init__(self):
        self.profile = {"ui_scale_percent": 150, "follow_desktop": False, "render_scale": 2}

    def get_profile(self, _path):
        return dict(self.profile)

    def set_profile(self, _path, profile):
        self.profile = dict(profile)


class EditorRow(Adw.ExpanderRow):
    def __init__(self, window, editor, *, fixture=None):
        super().__init__(title=editor_title(editor), subtitle="Reading settings…")
        self.window, self.editor = window, editor
        self.profile, self.integration = {}, {}
        self.loaded = False
        self.state = None
        self.running = None
        self.timer = None
        self.syncing = False
        self.discard_after_save = False
        self.override = Adw.SwitchRow(title="Override scale")
        self.override.connect("notify::active", self.override_changed)
        self.add_row(self.override)
        self.controls = Adw.ActionRow(title="Scale")
        self.adjustment = Gtk.Adjustment(value=150, lower=core.MIN_UI_SCALE,
                                         upper=core.MAX_UI_SCALE, step_increment=5, page_increment=10)
        self.spin = Gtk.SpinButton(adjustment=self.adjustment, numeric=True, digits=0,
                                   width_chars=4, valign=Gtk.Align.CENTER,
                                   update_policy=Gtk.SpinButtonUpdatePolicy.IF_VALID)
        self.spin.connect("changed", self.text_changed)
        self.spin.connect("output", self.preserve_invalid_text)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self.flush())
        self.spin.add_controller(focus)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.key_pressed)
        self.spin.add_controller(keys)
        self.controls.add_suffix(self.spin)
        self.controls.add_suffix(Gtk.Label(label="%", margin_end=6))
        self.controls.set_activatable_widget(self.spin)
        self.add_row(self.controls)
        notice_row = Adw.PreferencesRow()
        self.restart_notice = Gtk.Label(label="Close and reopen Unity to apply scale changes.",
                                        wrap=True, xalign=0, margin_start=18, margin_end=18,
                                        margin_top=10, margin_bottom=10)
        self.restart_notice.add_css_class("caption")
        self.restart_notice.add_css_class("dim-label")
        notice_row.set_child(self.restart_notice)
        self.add_row(notice_row)
        self.connect("notify::expanded", self.expanded_changed)
        options = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Editor options",
                                 valign=Gtk.Align.CENTER)
        options.add_css_class("flat")
        popover = Gtk.Popover()
        option_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=6,
                             margin_start=6, margin_end=6)
        details = Gtk.Button(label="Editor Details…")
        details.add_css_class("flat")
        details.connect("clicked", lambda *_: (popover.popdown(), window.editor_details(self)))
        option_box.append(details)
        self.project_button = Gtk.Button(label="Open a Project…")
        self.project_button.add_css_class("flat")
        self.project_button.connect("clicked", lambda *_: (popover.popdown(), window.open_project(self)))
        option_box.append(self.project_button)
        popover.set_child(option_box)
        options.set_popover(popover)
        self.add_suffix(options)
        self.update_controls()
        if fixture:
            self.set_state(*fixture)
        else:
            def read():
                from . import integration
                return (window.store.get_profile(editor.path), integration.status(editor.path),
                        core.get_running_scale(editor.path))
            window.worker(read, lambda result: self.set_state(*result))

    def set_state(self, profile, status, running=None):
        self.profile, self.integration, self.running = dict(profile), dict(status), running
        self.state = EditorEditState(profile.get("ui_scale_percent", 150), status.get("enabled", False))
        self.loaded = True
        self.sync_widgets()

    def sync_widgets(self):
        self.syncing = True
        if self.state.value is not None:
            self.adjustment.set_value(self.state.value)
        self.spin.set_text(self.state.text)
        self.override.set_active(self.state.override)
        self.syncing = False
        self.refresh()

    def refresh(self):
        if self.state:
            attention = self.integration.get("state") in ("conflict", "error")
            self.set_subtitle(self.state.subtitle(self.running, attention=attention))
            if self.state.value is None or self.state.error:
                self.spin.add_css_class("error")
            else:
                self.spin.remove_css_class("error")
        self.update_controls()
        self.window.update_actions()

    def current_profile(self, scale=None):
        value = scale if scale is not None else self.state.value
        return edited_profile(self.profile, value if value is not None else self.state.saved_scale, False)

    def update_controls(self):
        ready = self.loaded and not self.window.busy and not self.window.closing_mode and not self.discard_after_save
        self.override.set_sensitive(ready)
        self.controls.set_sensitive(ready and self.override.get_active())
        self.project_button.set_sensitive(ready and self.override.get_active() and
                                           bool(self.integration.get("enabled")) and not self.state.pending)

    def override_changed(self, *_):
        if self.syncing or not self.state:
            return
        self.state.set_override(self.override.get_active())
        self.refresh()
        self.flush()

    def text_changed(self, *_):
        if self.syncing or not self.state:
            return
        self.state.edit_text(self.spin.get_text())
        self.refresh()
        self.cancel_timer()
        if self.state.override and self.state.value is not None and self.state.dirty:
            self.timer = GLib.timeout_add(500, self.flush)

    def preserve_invalid_text(self, *_):
        if self.state and self.state.value is None and not self.syncing:
            # GTK otherwise replaces out-of-range input with its previous
            # value on focus loss. Keep it visible and unsaved instead.
            self.syncing = True
            self.spin.set_text(self.state.text)
            self.syncing = False
            return True
        return False

    def key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.flush()
            if self.state.value is None:
                self.window.error(core.AppError("Enter a whole scale from100% to200%."))
            return True
        return False

    def cancel_timer(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def flush(self):
        self.cancel_timer()
        if not self.state or self.window.smoke_test:
            return GLib.SOURCE_REMOVE
        request = self.state.begin()
        if request is None:
            self.refresh()
            self.window.maybe_finish_close()
            return GLib.SOURCE_REMOVE
        profile = self.current_profile(request.scale)
        self.refresh()
        def save():
            from . import integration
            with self.window.write_lock:
                actual = integration.status(self.editor.path)
                if request.override:
                    if actual.get("enabled"):
                        self.window.store.set_profile(self.editor.path, profile)
                        status = actual
                    else:
                        status = apply_editor_override(self.window.store, self.editor.path, profile, True)
                else:
                    status = integration.disable(self.editor.path)
                    if request.save_scale:
                        self.window.store.set_profile(self.editor.path, profile)
                return status, core.get_running_scale(self.editor.path)
        def saved(result):
            self.state.complete(request)
            self.integration, self.running = result
            if request.save_scale or request.override:
                self.profile = profile
            self.after_save()
        def failed(error):
            self.state.complete(request, error=error)
            if self.discard_after_save or self.window.closing_mode == "discard":
                self.discard_after_save = False
                self.state.discard()
                self.sync_widgets()
                self.window.maybe_finish_close()
                return
            self.set_expanded(True)
            self.refresh()
            self.window.closing_mode = None
            self.window.error(error)
            self.window.update_actions()
        self.window.worker(save, saved, failure=failed)
        return GLib.SOURCE_REMOVE

    def after_save(self):
        if self.discard_after_save or self.window.closing_mode == "discard":
            self.discard_after_save = False
            self.state.discard()
            self.sync_widgets()
        else:
            self.refresh()
            if self.state.dirty and self.state.value is not None and self.timer is None:
                self.timer = GLib.idle_add(self.flush)
        self.window.maybe_finish_close()

    def expanded_changed(self, *_):
        if self.syncing or self.discard_after_save or self.get_expanded() or not self.state or not self.state.pending:
            return
        if self.state.value is not None and not self.state.error:
            self.flush()
        else:
            self.window.confirm_pending([self], close=False)

    def discard(self):
        self.cancel_timer()
        if self.state.inflight is None:
            self.state.discard()
            self.sync_widgets()
        else:
            self.discard_after_save = True
            self.update_controls()


class UnityScaleWindow(Adw.ApplicationWindow):
    def __init__(self, application, *, smoke_test=False):
        super().__init__(application=application, title=core.APP_NAME,
                         default_width=760, default_height=520)
        self.smoke_test = smoke_test
        self.store = _MemoryStore() if smoke_test else core.Store()
        self.rows = []
        self.busy = False
        self.closed = False
        self._list_generation = 0
        self.write_lock = threading.Lock()
        self.closing_mode = None
        self.force_close = False
        self.pending_dialog = None
        self.connect("close-request", self._on_close)
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=core.APP_NAME))
        self.spinner = Gtk.Spinner()
        header.pack_start(self.spinner)
        menu = Gio.Menu()
        menu.append("Diagnostics", "app.diagnostics")
        menu.append("About Unity Scale", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        repository_url = getattr(core, "REPOSITORY_URL", "")
        self.github_button = Gtk.LinkButton(label="GitHub", uri=repository_url or "about:blank")
        self.github_button.set_sensitive(bool(repository_url))
        header.pack_end(self.github_button)
        toolbar.add_top_bar(header)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        toolbar.set_content(scroll)
        clamp = Adw.Clamp(maximum_size=700, tightening_threshold=500)
        scroll.set_child(clamp)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                          margin_start=24, margin_end=24, margin_top=24, margin_bottom=24)
        clamp.set_child(content)
        self.group = Adw.PreferencesGroup(title="Installed Editors")
        self.scan_button = Gtk.Button(label="Scan for Installed Editors")
        self.scan_button.connect("clicked", lambda *_: self.scan())
        self.add_button = Gtk.Button(label="Add Editor…")
        self.add_button.connect("clicked", lambda *_: self.locate())
        editor_actions = Gtk.Box(spacing=8)
        editor_actions.append(self.add_button)
        editor_actions.append(self.scan_button)
        self.group.set_header_suffix(editor_actions)
        content.append(self.group)
        self.empty = Adw.ActionRow(title="Scan to find installed Editors.")
        self.group.add(self.empty)
        if smoke_test:
            fixture = ({"ui_scale_percent": 150, "follow_desktop": False, "render_scale": 2},
                       {"enabled": False, "can_enable": True, "state": "disabled"})
            editors = [core.Editor("/smoke/Editor/Unity", "6000.3.27f2", "Unity 6.3 LTS", "Test")]
            self.set_editors(editors, fixture=fixture)
        else:
            self.worker(lambda: known_editors(self.store), self.set_editors)

    def _on_close(self, *_):
        if self.force_close or not any(row.state and row.state.pending for row in self.rows):
            self.closed = True
            for row in self.rows:
                row.cancel_timer()
            return False
        self.confirm_pending(self.rows, close=True)
        return True

    def worker(self, task, success, *, busy=False, failure=None):
        if busy:
            self.set_busy(True)
        def work():
            try:
                result, error = task(), None
            except Exception as exc:
                result, error = None, exc
            def complete():
                if self.closed:
                    return GLib.SOURCE_REMOVE
                if busy:
                    self.set_busy(False)
                if error:
                    (failure or self.error)(error)
                else:
                    success(result)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(complete)
        threading.Thread(target=work, name="unity-scale-worker", daemon=True).start()

    def set_busy(self, busy):
        self.busy = busy
        self.spinner.set_spinning(busy)
        self.update_actions()

    def update_actions(self):
        pending = any(row.state and row.state.pending for row in self.rows)
        ready = not self.busy and not pending and not self.closing_mode
        self.scan_button.set_sensitive(ready)
        self.add_button.set_sensitive(ready)
        self.get_application().lookup_action("locate").set_enabled(ready)
        for row in self.rows:
            row.update_controls()

    def confirm_pending(self, rows, *, close):
        if self.pending_dialog:
            self.pending_dialog.present()
            return
        pending = [row for row in rows if row.state and row.state.pending]
        if not pending:
            return
        malformed = any(row.state.value is None for row in pending)
        body = ("Enter a whole scale from100% to200% before saving." if malformed else
                "Some Editor changes have not finished saving.")
        if any(row.state.inflight for row in pending):
            body += " Changes already being saved will finish; Discard drops remaining unsaved edits."
        dialog = Adw.MessageDialog(transient_for=self, modal=True, heading="Save pending changes?", body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Discard")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("save", not malformed)
        dialog.set_default_response("cancel" if malformed else "save")
        dialog.set_close_response("cancel")
        self.pending_dialog = dialog
        def respond(_dialog, response):
            self.pending_dialog = None
            if response == "cancel":
                if not close:
                    for row in pending:
                        row.set_expanded(True)
                return
            if response == "discard":
                if close:
                    self.closing_mode = "discard"
                for row in pending:
                    row.discard()
                if not close:
                    for row in pending:
                        row.set_expanded(False)
            elif response == "save":
                if close:
                    self.closing_mode = "save"
                for row in pending:
                    row.flush()
            self.update_actions()
            self.maybe_finish_close()
        dialog.connect("response", respond)
        dialog.present()

    def maybe_finish_close(self):
        if not self.closing_mode:
            return
        if any(row.state and row.state.inflight for row in self.rows):
            return
        if self.closing_mode == "discard":
            for row in self.rows:
                if row.state:
                    row.discard()
        elif any(row.state and row.state.pending for row in self.rows):
            return
        self.force_close = True
        self.close()

    def set_editors(self, editors, *, fixture=None):
        self._list_generation += 1
        for row in self.rows:
            self.group.remove(row)
        self.rows = []
        if self.empty.get_parent() is not None:
            self.group.remove(self.empty)
        for editor in editors:
            row = EditorRow(self, editor, fixture=fixture)
            self.rows.append(row)
            self.group.add(row)
        if not self.rows:
            self.group.add(self.empty)

    def scan(self):
        if self.smoke_test or self.busy:
            return
        def discover():
            editors = core.discover_editors(editor_paths(self.store.load()))
            for editor in editors:
                self.store.add_editor(editor.path)
            return editors
        def found(editors):
            self.set_editors(editors)
            if not editors:
                self.toast("No installed Editors found. Use Locate Editor to add one.")
        self.worker(discover, found, busy=True)

    def locate(self):
        if self.smoke_test or self.busy:
            return
        dialog = Gtk.FileDialog(title="Locate the Unity Editor executable", accept_label="Add Editor")
        def chosen(file_dialog, result):
            try:
                file = file_dialog.open_finish(result)
                path = file.get_path()
                if not path:
                    raise core.AppError("Choose an Editor on this computer.")
            except GLib.Error as exc:
                if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    self.error(exc)
                return
            except core.AppError as exc:
                self.error(exc)
                return
            def add():
                self.store.add_editor(path)
                return known_editors(self.store)
            self.worker(add, self.set_editors, busy=True)
        dialog.open(self, None, chosen)

    def editor_details(self, row):
        detail = row.integration.get("detail", "")
        body = f"{row.editor.path}\n\n{detail}"
        if row.integration.get("enabled"):
            body += "\n\nThe Editor launch path uses the Unity Scale wrapper. Its original executable is kept as a verified backup. No new Unity shortcut is created."
        dialog = Adw.MessageDialog(transient_for=self, modal=True, heading=editor_title(row.editor), body=body)
        dialog.add_response("close", "Close")
        dialog.present()

    def open_project(self, row):
        if self.smoke_test or self.busy or not row.integration.get("enabled"):
            return
        dialog = Gtk.FileDialog(title="Open a Unity project", accept_label="Open Project")
        def chosen(file_dialog, result):
            try:
                folder = file_dialog.select_folder_finish(result)
                project = folder.get_path()
                if not project or not (Path(project) / "ProjectSettings/ProjectVersion.txt").is_file():
                    raise core.AppError("Choose the root folder of a Unity project.")
            except GLib.Error as exc:
                if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    self.error(exc)
                return
            except core.AppError as exc:
                self.error(exc)
                return
            profile = row.current_profile()
            self.worker(lambda: start_editor(self.store, row.editor.path, profile, project),
                        lambda _result: self.toast("Opening Unity."), busy=True)
        dialog.select_folder(self, None, chosen)

    def toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=message))

    def error(self, error):
        dialog = Adw.MessageDialog(transient_for=self, modal=True,
                                   heading="Unity Scale couldn’t complete that action", body=str(error))
        dialog.add_response("close", "Close")
        dialog.present()

    def diagnostics(self):
        def collect():
            report = core.diagnostics()
            report["editors"] = [{"version": row.editor.version,
                                   "integration_enabled": bool(row.integration.get("enabled")),
                                   "profile": {key: row.profile[key] for key in
                                               ("ui_scale_percent", "follow_desktop", "render_scale") if key in row.profile}}
                                  for row in self.rows]
            return json.dumps(report, indent=2, ensure_ascii=False)
        self.worker(collect, self.present_diagnostics)

    def present_diagnostics(self, snapshot):
        window = Adw.Window(title="Diagnostics", transient_for=self, default_width=680, default_height=540)
        toolbar = Adw.ToolbarView()
        window.set_content(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Diagnostics"))
        copy = Gtk.Button(label="Copy")
        copy.connect("clicked", lambda *_: self.get_clipboard().set(snapshot))
        header.pack_end(copy)
        toolbar.add_top_bar(header)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_start=18, margin_end=18, margin_top=18, margin_bottom=18)
        logs = Gtk.Label(label=f"Local logs: {core.Store().state_dir}\nThe copied report excludes paths and raw logs.",
                         wrap=True, selectable=True, xalign=0)
        logs.add_css_class("caption")
        content.append(logs)
        text = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=12, right_margin=12,
                            top_margin=12, bottom_margin=12)
        text.get_buffer().set_text(snapshot)
        scroll = Gtk.ScrolledWindow(vexpand=True, child=text)
        scroll.add_css_class("card")
        content.append(scroll)
        toolbar.set_content(content)
        window.present()

    def about(self):
        dialog = Adw.AboutWindow(transient_for=self, modal=True, application_name=core.APP_NAME,
            application_icon=core.APP_ID, version=core.VERSION, developer_name="Unity Scale contributors",
            comments="Independent Unity Editor scaling for Linux.\n\nEnabling integration wraps the selected Editor’s launch path and keeps the original executable as a verified backup. No new Unity shortcut is created.")
        dialog.add_credit_section("Built with", ["GTK and libadwaita", "xwayland-satellite · MPL-2.0"])
        dialog.present()


class UnityScaleApplication(Adw.Application):
    def __init__(self, *, smoke_test=False):
        super().__init__(application_id=core.APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE if smoke_test else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.smoke_test = smoke_test
        self.window = None
        self.startup_error = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display:
            Gtk.IconTheme.get_for_display(display).add_search_path(str(Path(__file__).resolve().parent.parent / "resources"))
        for name in ["locate", "diagnostics", "about"]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _parameter, method=name:
                           getattr(self.window, method)() if self.window else None)
            self.add_action(action)
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", lambda *_: self.window.close() if self.window else self.quit())
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

    def do_activate(self):
        if self.window is None:
            try:
                self.window = UnityScaleWindow(self, smoke_test=self.smoke_test)
            except Exception as exc:
                self.startup_error = exc
                self.quit()
                return
        if self.smoke_test:
            GLib.idle_add(self.smoke_check)
        else:
            self.window.present()

    def smoke_check(self):
        try:
            window = self.window
            assert len(window.rows) == 1
            assert window.add_button.get_label() == "Add Editor…"
            assert isinstance(window.github_button, Gtk.LinkButton)
            assert window.github_button.get_uri() == (getattr(core, "REPOSITORY_URL", "") or "about:blank")
            row = window.rows[0]
            assert row.restart_notice.get_label() == "Close and reopen Unity to apply scale changes."
            assert row.get_title() == "Unity 6.3 LTS (6000.3.27f2)"
            assert row.state.saved_scale == 150
            row.set_state({"ui_scale_percent": 160, "follow_desktop": False, "render_scale": 2},
                          {"enabled": False, "state": "disabled"})
            row.spin.emit("change-value", Gtk.ScrollType.STEP_FORWARD)
            assert row.state.value == 165, "Loaded numeric value must drive the native increment"
            row.set_state({"ui_scale_percent": 150, "follow_desktop": False, "render_scale": 2},
                          {"enabled": False, "state": "disabled"})
            assert not row.controls.get_sensitive()
            row.override.set_active(True)
            row.spin.set_text("160")
            assert row.controls.get_sensitive()
            assert row.state.value == 160 and row.state.dirty
            assert window.store.profile["ui_scale_percent"] == 150
            row.spin.set_text("999")
            row.spin.update()
            assert row.state.value is None and row.spin.get_text() == "999"
            assert row.state.pending
            row.state.discard()
            row.sync_widgets()
            assert not row.state.pending
            assert row.get_subtitle() == "Override off"
            assert not window.get_visible()
            print("Unity Scale GTK smoke test passed (no windows shown, no settings or Editor changed).")
        except Exception as exc:
            self.startup_error = exc
        finally:
            self.window.destroy()
            self.quit()
        return GLib.SOURCE_REMOVE


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    smoke_test = "--smoke-test" in arguments
    arguments = [arg for arg in arguments if arg != "--smoke-test"]
    if not Gtk.init_check():
        print("Unity Scale needs a graphical desktop. Use the CLI for command-line operations.", file=sys.stderr)
        return 2
    app = UnityScaleApplication(smoke_test=smoke_test)
    result = app.run(["unity-scale", *arguments])
    if app.startup_error:
        print(f"Unity Scale: {app.startup_error}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
