"""Focused GTK settings interface. This app never launches or patches Unity."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import threading

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import core
from .gui_state import EditorEditState


def editor_name(version):
    series = '.'.join(version.split('.')[:2])
    return {'6000.3': 'Unity 6.3 LTS', '6000.0': 'Unity 6 LTS',
            '2022.3': 'Unity 2022.3 LTS', '2021.3': 'Unity 2021.3 LTS'}.get(series, 'Unity Editor')


@dataclass
class EditorSession:
    editor: core.Editor
    profile: dict
    state: EditorEditState
    timer: int | None = None
    backend: dict = field(default_factory=dict)


class UnityScaleWindow(Adw.ApplicationWindow):
    def __init__(self, application, *, store=None, editors=None):
        super().__init__(application=application, title=core.APP_NAME, default_width=760, default_height=520)
        self.store = store if store is not None else core.Store()
        self.sessions = {}
        self.rows = {}
        self.session = None
        self.syncing = False
        self.closed = False
        self.force_close = False
        self.busy = False
        self.closing_mode = None
        self.pending_dialog = None
        self.write_lock = threading.Lock()
        self.connect('close-request', self.on_close)
        self.overlay = Adw.ToastOverlay()
        self.set_content(self.overlay)
        toolbar = Adw.ToolbarView()
        self.overlay.set_child(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=core.APP_NAME))
        menu = Gio.Menu()
        for label, action in [('Add Editor…', 'add'), ('Diagnostics', 'diagnostics'), ('GitHub', 'github'), ('About', 'about')]:
            menu.append(label, 'app.' + action)
        header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu))
        toolbar.add_top_bar(header)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        toolbar.set_content(scroll)
        clamp = Adw.Clamp(maximum_size=740, tightening_threshold=580)
        scroll.set_child(clamp)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22,
                          margin_start=24, margin_end=24, margin_top=22, margin_bottom=24)
        clamp.set_child(content)
        searchbar = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text='Search Editors', hexpand=True)
        self.search.connect('search-changed', lambda *_: self.filter_editors())
        searchbar.append(self.search)
        self.add_button = Gtk.Button(icon_name='list-add-symbolic', tooltip_text='Add Editor')
        self.add_button.connect('clicked', lambda *_: self.add_editor())
        searchbar.append(self.add_button)
        self.scan_button = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Scan for installed Editors')
        self.scan_button.connect('clicked', lambda *_: self.scan())
        searchbar.append(self.scan_button)
        content.append(searchbar)
        self.editor_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.editor_list.add_css_class('boxed-list')
        self.editor_list.connect('row-selected', self.row_selected)
        content.append(self.editor_list)
        self.empty = Adw.StatusPage(title='No Editors found', icon_name='edit-find-symbolic')
        self.empty.set_visible(False)
        content.append(self.empty)
        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        content.append(self.controls)
        scaling = Adw.PreferencesGroup(title='Scaling')
        self.controls.append(scaling)
        self.custom = Adw.SwitchRow(title='Custom scale')
        self.custom.connect('notify::active', self.custom_changed)
        scaling.add(self.custom)
        self.scale_row = Adw.ActionRow(title='Scale')
        scaling.add(self.scale_row)
        scale_controls = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        self.adjustment = Gtk.Adjustment(value=150, lower=100, upper=200, step_increment=1, page_increment=10)
        self.slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.adjustment,
                                draw_value=False, width_request=200, valign=Gtk.Align.CENTER)
        scale_controls.append(self.slider)
        self.spin = Gtk.SpinButton(adjustment=self.adjustment, numeric=True, digits=0, width_chars=4,
                                   update_policy=Gtk.SpinButtonUpdatePolicy.IF_VALID, valign=Gtk.Align.CENTER)
        scale_controls.append(self.spin)
        scale_controls.append(Gtk.Label(label='%'))
        self.scale_row.add_suffix(scale_controls)
        self.spin.connect('changed', self.number_changed)
        self.spin.connect('output', self.preserve_invalid)
        self.slider.connect('value-changed', self.slider_changed)
        focus = Gtk.EventControllerFocus()
        focus.connect('leave', lambda *_: self.flush())
        self.spin.add_controller(focus)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.number_key)
        self.spin.add_controller(keys)
        footer = Gtk.Box(spacing=10)
        self.backend_note = Gtk.Button(label='Native scaling unavailable', halign=Gtk.Align.START, hexpand=True)
        self.backend_note.add_css_class('flat')
        self.backend_note.add_css_class('caption')
        self.backend_note.connect('clicked', lambda *_: self.backend_details())
        footer.append(self.backend_note)
        self.status_label = Gtk.Label(label='Saved', valign=Gtk.Align.CENTER)
        self.status_label.add_css_class('caption')
        self.status_label.add_css_class('dim-label')
        footer.append(self.status_label)
        self.controls.append(footer)
        self.controls.set_visible(False)
        if editors is not None:
            self.set_editors([(editor, self.store.get_profile(editor.path)) for editor in editors])
        else:
            self.scan()

    def worker(self, task, done, failed=None):
        def work():
            try:
                result, error = task(), None
            except Exception as exc:
                result, error = None, exc
            def finish():
                if self.closed:
                    return GLib.SOURCE_REMOVE
                if error is not None:
                    (failed or self.error)(error)
                else:
                    done(result)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(finish)
        threading.Thread(target=work, name='unity-scale-settings', daemon=True).start()

    def scan(self, extra=None):
        if self.busy or self.has_pending() or self.closing_mode:
            return
        self.busy = True
        self.update_actions()
        def discover():
            editors = core.discover_editors(extra, store=self.store)
            from .native_backend import status
            return [(editor, self.store.get_profile(editor.path), status(editor.path, self.store.get_profile(editor.path), settings_path=self.store.path)) for editor in editors]
        def found(values):
            self.busy = False
            self.set_editors(values)
        def failed(exc):
            self.busy = False
            self.update_actions()
            self.error(exc)
        self.worker(discover, found, failed)

    def set_editors(self, values):
        previous = self.session.editor.path if self.session else None
        self.syncing = True
        self.editor_list.remove_all()
        self.rows.clear()
        from .native_backend import status
        for item in values:
            editor, profile = item[:2]
            backend = item[2] if len(item) > 2 else status(editor.path, profile, settings_path=self.store.path)
            if editor.path not in self.sessions:
                state = EditorEditState(profile['ui_scale_percent'], profile['override_enabled'])
                self.sessions[editor.path] = EditorSession(editor, dict(profile), state)
            else:
                self.sessions[editor.path].editor = editor
            self.sessions[editor.path].backend = backend
            row = Adw.ActionRow(title=editor_name(editor.version), subtitle=editor.version,
                                activatable=True, selectable=True)
            row.editor_path = editor.path
            icon_path = Path(editor.path).parent / 'Data/Resources/LargeUnityIcon.png'
            icon = Gtk.Image.new_from_file(str(icon_path)) if icon_path.is_file() else Gtk.Image.new_from_icon_name('applications-engineering-symbolic')
            icon.set_pixel_size(34)
            row.add_prefix(icon)
            options = Gtk.MenuButton(icon_name='view-more-symbolic', valign=Gtk.Align.CENTER, tooltip_text='Editor options')
            popover = Gtk.Popover()
            actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
            details = Gtk.Button(label='Editor details')
            details.add_css_class('flat')
            details.connect('clicked', lambda _, e=editor, p=popover: (p.popdown(), self.editor_details(e)))
            actions.append(details)
            location = Gtk.Button(label='Show in Files')
            location.add_css_class('flat')
            location.connect('clicked', lambda _, e=editor, p=popover: (p.popdown(), self.show_folder(e)))
            actions.append(location)
            popover.set_child(actions)
            options.set_popover(popover)
            row.add_suffix(options)
            self.rows[editor.path] = row
            self.editor_list.append(row)
        self.syncing = False
        self.filter_editors(preferred=previous)
        self.update_actions()

    def filter_editors(self, preferred=None):
        query = self.search.get_text().strip().casefold()
        visible = []
        for path, row in self.rows.items():
            editor = self.sessions[path].editor
            matches = query in (editor_name(editor.version) + ' ' + editor.version + ' ' + path).casefold()
            row.set_visible(matches)
            if matches:
                visible.append(path)
        self.empty.set_title('No matching Editors' if query else 'No Editors found')
        self.empty.set_visible(not visible)
        self.editor_list.set_visible(bool(visible))
        self.controls.set_visible(bool(visible))
        if visible:
            path = preferred or (self.session.editor.path if self.session else None)
            if path in self.rows and path not in visible:
                # Filtering the list must not silently change the edited Editor.
                self.editor_list.unselect_all()
                self.controls.set_visible(False)
            else:
                self.select_editor(path if path in visible else visible[0])

    def select_editor(self, path):
        if path not in self.rows:
            return
        self.editor_list.select_row(self.rows[path])
        if self.session is not self.sessions[path]:
            self.activate_session(self.sessions[path])

    def row_selected(self, _list, row):
        if row is not None and not self.syncing:
            self.activate_session(self.sessions[row.editor_path])

    def activate_session(self, session):
        self.session = session
        self.controls.set_visible(self.rows[session.editor.path].get_visible())
        self.syncing = True
        try:
            state = session.state
            self.custom.set_active(state.override)
            self.adjustment.set_value(state.value if state.value is not None else state.saved_scale)
            self.spin.set_text(state.text)
        finally:
            self.syncing = False
        self.refresh()

    def custom_changed(self, *_):
        if self.syncing or self.session is None:
            return
        state = self.session.state
        enabled = self.custom.get_active()
        if not enabled and state.value is None:
            state.edit_text(str(state.saved_scale))
            self.syncing = True
            self.spin.set_text(state.text)
            self.syncing = False
        state.set_override(enabled)
        self.refresh()
        self.flush()

    def number_changed(self, *_):
        if self.syncing or self.session is None:
            return
        state = self.session.state
        state.edit_text(self.spin.get_text())
        if state.value is not None and self.adjustment.get_value() != state.value:
            text, position = self.spin.get_text(), self.spin.get_position()
            self.syncing = True
            try:
                self.adjustment.set_value(state.value)
                self.spin.set_text(text)
                self.spin.set_position(position)
            finally:
                self.syncing = False
        self.refresh()
        self.queue_save(self.session)

    def slider_changed(self, *_):
        if self.syncing or self.session is None:
            return
        state = self.session.state
        state.edit_text(str(int(round(self.adjustment.get_value()))))
        self.refresh()
        self.queue_save(self.session)

    def preserve_invalid(self, *_):
        if self.session and self.session.state.value is None and not self.syncing:
            self.syncing = True
            self.spin.set_text(self.session.state.text)
            self.syncing = False
            return True
        return False

    def number_key(self, _controller, key, _keycode, _state):
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.flush()
            return True
        if key == Gdk.KEY_Escape and self.session and self.session.state.inflight is None:
            self.cancel_timer(self.session)
            self.session.state.discard()
            self.activate_session(self.session)
            return True
        return False

    def queue_save(self, session):
        self.cancel_timer(session)
        if session.state.value is not None and session.state.dirty and not session.state.error:
            def save():
                session.timer = None
                self.flush(session)
                return GLib.SOURCE_REMOVE
            session.timer = GLib.timeout_add(500, save)

    def cancel_timer(self, session):
        if session.timer is not None:
            GLib.source_remove(session.timer)
            session.timer = None

    def flush(self, session=None):
        session = session or self.session
        if session is None:
            return GLib.SOURCE_REMOVE
        self.cancel_timer(session)
        request = session.state.begin()
        if request is None:
            self.refresh()
            self.maybe_finish_close()
            return GLib.SOURCE_REMOVE
        choice = dict(session.profile, override_enabled=request.override, ui_scale_percent=request.scale, follow_desktop=False)
        def save():
            with self.write_lock:
                before, after = self.store.set_profile_change(session.editor.path, choice)
                from .native_backend import status
                return before, after, status(session.editor.path, after, settings_path=self.store.path)
        def saved(result):
            _before, after, backend = result
            session.state.complete(request)
            session.profile = dict(after)
            session.backend = backend
            if self.closing_mode == 'discard':
                session.state.discard()
                if self.session is session:
                    self.activate_session(session)
            elif session.state.dirty and session.state.value is not None:
                self.queue_save(session)
            self.refresh()
            self.maybe_finish_close()
        def failed(error):
            session.state.complete(request, error=error)
            if self.closing_mode == 'discard':
                session.state.discard()
                if self.session is session:
                    self.activate_session(session)
                self.maybe_finish_close()
            else:
                self.closing_mode = None
                self.refresh()
                self.error(error)
        self.worker(save, saved, failed)
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        if self.session is not None:
            state = self.session.state
            self.backend_note.set_label('Uses saved setting on next launch' if self.session.backend.get('connected') else 'Native scaling not connected')
            self.custom.set_subtitle('' if state.override else 'Unity default')
            self.scale_row.set_sensitive(state.override and not self.closing_mode)
            self.custom.set_sensitive(not self.closing_mode)
            if state.value is None:
                self.spin.add_css_class('error')
                self.status_label.set_label('Invalid scale · not saved')
            else:
                self.spin.remove_css_class('error')
                self.status_label.set_label('Not saved' if state.error else 'Saving…' if state.inflight else 'Unsaved' if state.dirty else 'Saved')
        self.update_actions()

    def has_pending(self):
        return any(session.state.pending for session in self.sessions.values())

    def update_actions(self):
        ready = not self.busy and not self.closing_mode and not self.has_pending()
        self.scan_button.set_sensitive(ready)
        self.add_button.set_sensitive(ready)
        self.get_application().lookup_action('add').set_enabled(ready)

    def add_editor(self):
        if self.busy or self.has_pending():
            return
        dialog = Gtk.FileDialog(title='Add Unity Editor', accept_label='Add Editor')
        def chosen(file_dialog, result):
            try:
                file = file_dialog.open_finish(result)
                path = file.get_path()
                if not path:
                    raise core.AppError('Choose an Editor on this computer.')
            except GLib.Error as exc:
                if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    self.error(exc)
                return
            except core.AppError as exc:
                self.error(exc)
                return
            self.worker(lambda: self.store.add_editor(path), lambda editor: self.scan([editor.path]))
        dialog.open(self, None, chosen)

    def show_folder(self, editor):
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(Path(editor.path).parent)))
        def done(obj, result):
            try:
                obj.launch_finish(result)
            except GLib.Error as exc:
                self.error(exc)
        launcher.launch(self, None, done)

    def editor_details(self, editor):
        dialog = Adw.MessageDialog(transient_for=self, heading=editor_name(editor.version),
                                  body=editor.version + '\n\n' + editor.path, modal=True)
        dialog.add_response('close', 'Close')
        dialog.present()

    def backend_details(self):
        dialog = Adw.MessageDialog(transient_for=self, modal=True, heading='Unity scaling',
            body=((self.session.backend.get('message') if self.session else None) or 'Native scaling is not connected to this Editor.') + '\n\nSaved settings are separate from the current running Editor. Saving does not change desktop scale.')
        dialog.add_response('close', 'Close')
        dialog.present()

    def error(self, error):
        dialog = Adw.MessageDialog(transient_for=self, modal=True, heading='Could not complete that action', body=str(error))
        dialog.add_response('close', 'Close')
        dialog.present()

    def on_close(self, *_):
        if self.force_close or not self.has_pending():
            self.closed = True
            for session in self.sessions.values():
                self.cancel_timer(session)
            return False
        self.confirm_pending()
        return True

    def confirm_pending(self):
        if self.pending_dialog is not None:
            self.pending_dialog.present()
            return
        invalid = any(s.state.pending and s.state.value is None for s in self.sessions.values())
        body = 'Enter a whole scale from 100% to 200% before saving.' if invalid else 'Some settings have not finished saving.'
        if any(s.state.inflight for s in self.sessions.values()):
            body += '\n\nA save already in progress will finish. Discard skips later edits.'
        dialog = Adw.MessageDialog(transient_for=self, modal=True, heading='Save pending changes?',
            body=body)
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('discard', 'Discard')
        dialog.add_response('save', 'Save')
        dialog.set_response_appearance('discard', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance('save', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled('save', not invalid)
        dialog.set_default_response('cancel' if invalid else 'save')
        dialog.set_close_response('cancel')
        self.pending_dialog = dialog
        def response(_dialog, result):
            self.pending_dialog = None
            if result == 'cancel':
                return
            self.closing_mode = result
            for session in self.sessions.values():
                self.cancel_timer(session)
                if result == 'discard' and session.state.inflight is None:
                    session.state.discard()
                elif result == 'save':
                    self.flush(session)
            self.refresh()
            self.maybe_finish_close()
        dialog.connect('response', response)
        dialog.present()

    def maybe_finish_close(self):
        if not self.closing_mode:
            return
        if any(s.state.inflight for s in self.sessions.values()):
            return
        if self.closing_mode == 'discard':
            for session in self.sessions.values():
                session.state.discard()
        elif self.has_pending():
            return
        self.force_close = True
        self.close()

    def diagnostics(self):
        report = core.diagnostics()
        report['editors'] = [{'version': s.editor.version, 'saved': {
            'override_enabled': s.profile['override_enabled'], 'ui_scale_percent': s.profile['ui_scale_percent']}}
            for s in self.sessions.values()]
        dialog = Adw.Window(title='Diagnostics', transient_for=self, default_width=620, default_height=470)
        toolbar = Adw.ToolbarView()
        dialog.set_content(toolbar)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='Diagnostics'))
        button = Gtk.Button(label='Copy')
        snapshot = json.dumps(report, indent=2)
        button.connect('clicked', lambda *_: self.get_clipboard().set(snapshot))
        header.pack_end(button)
        toolbar.add_top_bar(header)
        view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            left_margin=16, right_margin=16, top_margin=16, bottom_margin=16)
        view.get_buffer().set_text(snapshot)
        toolbar.set_content(Gtk.ScrolledWindow(child=view))
        dialog.present()

    def about(self):
        dialog = Adw.AboutWindow(transient_for=self, application_name=core.APP_NAME,
            application_icon=core.ICON_NAME, version=core.VERSION, developer_name='Fardin Haque and contributors',
            comments='Native startup scaling prerelease for Unity 6000.3.27f2 on KDE Wayland with OpenGL. Restart Unity after changes. Running scale and physical-input/performance acceptance are not verified by this app.')
        dialog.present()


class UnityScaleApplication(Adw.Application):
    def __init__(self, *, store=None, editors=None):
        testing = store is not None or editors is not None
        super().__init__(application_id=core.APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE if testing else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.store_override = store
        self.editors_override = editors
        self.window = None
        self.startup_error = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display:
            Gtk.IconTheme.get_for_display(display).add_search_path(str(core.ROOT / 'resources'))
            Gtk.Window.set_default_icon_name(core.ICON_NAME)
        for name in ('add', 'diagnostics', 'about', 'github', 'quit'):
            action = Gio.SimpleAction.new(name, None)
            def activate(_action, _parameter, key=name):
                if self.window is None:
                    return
                if key == 'add':
                    self.window.add_editor()
                elif key == 'github':
                    Gtk.show_uri(self.window, core.REPOSITORY_URL, Gdk.CURRENT_TIME)
                elif key == 'quit':
                    self.window.close()
                else:
                    getattr(self.window, key)()
            action.connect('activate', activate)
            self.add_action(action)
        self.set_accels_for_action('app.quit', ['<primary>q'])
        self.set_accels_for_action('app.add', ['<primary>o'])

    def do_activate(self):
        if self.window is None:
            try:
                self.window = UnityScaleWindow(self, store=self.store_override, editors=self.editors_override)
            except Exception as exc:
                self.startup_error = exc
                self.quit()
                return
        self.window.present()


def main(argv=None):
    if not Gtk.init_check():
        print(core.APP_NAME + ' needs a graphical desktop.', file=sys.stderr)
        return 2
    app = UnityScaleApplication()
    result = app.run(['unity-scale', *(argv or [])])
    if app.startup_error is not None:
        print(core.APP_NAME + ': ' + str(app.startup_error), file=sys.stderr)
        return 1
    return result
