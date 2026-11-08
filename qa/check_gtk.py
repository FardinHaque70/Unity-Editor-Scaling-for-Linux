#!/usr/bin/python3
"""Actual-widget QA worker. Run through run_checks.py, never on the desktop."""
from __future__ import annotations

import faulthandler
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

faulthandler.enable()
APP = Path(os.environ.get("QA_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(APP))
if os.environ.get("GDK_BACKEND") != "broadway" or not os.environ.get("QA_STORE", "").startswith("/tmp/unity-scale-gtk-qa-"):
    raise SystemExit("Use qa/run_checks.py: isolated Broadway and temporary Store are required")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, GLib, Graphene, Gsk, Gtk
from unity_scale import core
# This suite exercises widgets with inert Editor files, not native delivery.
# Native integration has its own compiled fixtures and real-Unity acceptance.
from unittest.mock import patch
_ui_native_stub = patch('unity_scale.native_backend.ensure_connected', return_value={'connected': True})
_ui_native_stub.start()
from unity_scale.gui import UnityScaleApplication, UnityScaleWindow

OUTPUT = Path(os.environ["QA_OUTPUT"])
checks = []


def pump(seconds=0.04):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        for _ in range(100):
            if not context.pending():
                break
            context.iteration(False)
        time.sleep(0.003)


def until(predicate, description, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        pump()
    raise AssertionError("Timed out: " + description)


def verify(name, condition, **facts):
    checks.append(dict(name=name, passed=bool(condition), **facts))
    if not condition:
        raise AssertionError(f"{name}: {facts}")


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


def labels(widget):
    found = []
    if isinstance(widget, Gtk.Label):
        found.append(widget.get_label())
    child = widget.get_first_child()
    while child:
        found.extend(labels(child))
        child = child.get_next_sibling()
    return found


def snapshot_png(snapshot, filename, width, height):
    """Render the real GTK snapshot using C ABI, avoiding old GI node boxing.

    PyGObject3.46 cannot marshal concrete GskContainerNode return values from
    Gtk.Snapshot.to_node(). The snapshot and render graph are unchanged; only
    the renderer calls cross ctypes instead of that unsupported GI conversion.
    Each transferred native reference is released before returning.
    """
    gtk = ctypes.CDLL('libgtk-4.so.1')
    objects = ctypes.CDLL('libgobject-2.0.so.0')
    glib = ctypes.CDLL('libglib-2.0.so.0')
    capsule_pointer = ctypes.pythonapi.PyCapsule_GetPointer
    capsule_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    capsule_pointer.restype = ctypes.c_void_p

    class Rectangle(ctypes.Structure):
        _fields_ = [('x', ctypes.c_float), ('y', ctypes.c_float),
                    ('width', ctypes.c_float), ('height', ctypes.c_float)]

    class Error(ctypes.Structure):
        _fields_ = [('domain', ctypes.c_uint), ('code', ctypes.c_int), ('message', ctypes.c_char_p)]

    gtk.gtk_snapshot_to_node.argtypes = [ctypes.c_void_p]
    gtk.gtk_snapshot_to_node.restype = ctypes.c_void_p
    gtk.gsk_cairo_renderer_new.argtypes = []
    gtk.gsk_cairo_renderer_new.restype = ctypes.c_void_p
    gtk.gsk_renderer_realize.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    gtk.gsk_renderer_realize.restype = ctypes.c_int
    gtk.gsk_renderer_render_texture.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Rectangle)]
    gtk.gsk_renderer_render_texture.restype = ctypes.c_void_p
    gtk.gdk_texture_save_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    gtk.gdk_texture_save_to_png.restype = ctypes.c_int
    gtk.gdk_texture_get_width.argtypes = gtk.gdk_texture_get_height.argtypes = [ctypes.c_void_p]
    gtk.gdk_texture_get_width.restype = gtk.gdk_texture_get_height.restype = ctypes.c_int
    gtk.gsk_renderer_unrealize.argtypes = [ctypes.c_void_p]
    gtk.gsk_renderer_unrealize.restype = None
    gtk.gsk_render_node_unref.argtypes = [ctypes.c_void_p]
    gtk.gsk_render_node_unref.restype = None
    objects.g_object_unref.argtypes = [ctypes.c_void_p]
    objects.g_object_unref.restype = None
    glib.g_error_free.argtypes = [ctypes.c_void_p]
    glib.g_error_free.restype = None
    node = gtk.gtk_snapshot_to_node(capsule_pointer(snapshot.__gpointer__, None))
    if not node:
        raise AssertionError('GTK produced an empty snapshot')
    renderer = texture = None
    realized = False
    try:
        renderer = gtk.gsk_cairo_renderer_new()
        if not renderer:
            raise AssertionError('GTK could not allocate a Cairo renderer')
        error = ctypes.c_void_p()
        realized = bool(gtk.gsk_renderer_realize(renderer, None, ctypes.byref(error)))
        message = ''
        if error:
            message = ctypes.cast(error, ctypes.POINTER(Error)).contents.message.decode(errors='replace')
            glib.g_error_free(error)
        if not realized:
            raise AssertionError('GTK Cairo renderer could not be realized: ' + message)
        bounds = Rectangle(0, 0, width, height)
        texture = gtk.gsk_renderer_render_texture(renderer, node, ctypes.byref(bounds))
        if not texture or gtk.gdk_texture_get_width(texture) != width or gtk.gdk_texture_get_height(texture) != height:
            raise AssertionError('GTK produced a missing or incorrectly sized texture')
        return bool(gtk.gdk_texture_save_to_png(texture, os.fsencode(filename)))
    finally:
        if texture:
            objects.g_object_unref(texture)
        if realized:
            gtk.gsk_renderer_unrealize(renderer)
        if renderer:
            objects.g_object_unref(renderer)
        gtk.gsk_render_node_unref(node)


def capture(window, name):
    width, height = 760, 520
    window.set_default_size(width, height)
    window.allocate(width, height, -1, None)
    pump(0.15)
    def refresh_render(widget):
        # No browser drives Broadway's frame acknowledgements. Resolve pending
        # CSS state and invalidate child render caches before a direct snapshot.
        widget.get_style_context().get_color()
        widget.queue_draw()
        child = widget.get_first_child()
        while child:
            refresh_render(child)
            child = child.get_next_sibling()
    refresh_render(window)
    snap = Gtk.Snapshot.new()
    snap.render_background(window.get_style_context(), 0, 0, width, height)
    window.do_snapshot(window, snap)
    verify("capture-" + name, snapshot_png(snap, OUTPUT / (name + ".png"), width, height),
           width=width, height=height, renderer='actual GTK GskCairoRenderer C ABI')


class RecordingStore(core.Store):
    """Real temp atomic Store; a short write delay exposes close/save races."""
    def __init__(self, root):
        super().__init__(root)
        self.calls = []

    def set_profile_change(self, path, profile):
        time.sleep(0.10)
        before, saved = super().set_profile_change(path, profile)
        self.calls.append(dict(path=path, thread=threading.get_ident(), saved=dict(saved)))
        return before, saved


def main():
    window = None
    completed = False
    try:
        Adw.init()
        Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
        store = RecordingStore(Path(os.environ["QA_STORE"]))
        first = core.Editor("/qa/Unity/6000.3.27f2/Editor/Unity", "6000.3.27f2", "Unity 6.3 LTS", "QA metadata")
        second = core.Editor("/qa/Unity/2022.3.62f1/Editor/Unity", "2022.3.62f1", "Unity 2022.3 LTS", "QA metadata")
        app = UnityScaleApplication(store=store, editors=[first, second])
        app.register(None)
        window = UnityScaleWindow(app, store=store, editors=[first, second])
        window.present()
        pump(0.25)
        verify("product-name", window.get_title() == "Unity Editor Scaling for Linux", title=window.get_title())
        verify("two-editor-metadata-fixtures", len(window.sessions) == 2)
        obsolete = ("changes", "change_group", "settings_tab", "launcher_tab", "copy_button", "preview_tab", "save_button")
        verify("changes-ui-fully-removed", not any(hasattr(window, name) for name in obsolete)
               and "Changes" not in labels(window) and not any(isinstance(widget, Gtk.TextView) for widget in descendants(window)))
        headers = [widget for widget in descendants(window) if isinstance(widget, Adw.HeaderBar)]
        header_images = [widget for header in headers for widget in descendants(header) if isinstance(widget, Gtk.Image)]
        verify("no-app-drawn-header-logo", len(headers) == 1 and not any(
            widget.get_property("file") or widget.get_icon_name() == core.ICON_NAME for widget in header_images))
        window.select_editor(first.path)
        verify("default-remembers-150", store.get_profile(first.path)["ui_scale_percent"] == 150 and not window.custom.get_active())
        capture(window, "simple-default")
        # On bundled GTK4.12 the redundant ActionRow title was compressed to
        # individual letters by the slider/spin suffix. Check actual allocation
        # and text layout, rather than merely checking the saved scale value.
        title_labels = [widget for widget in descendants(window.scale_row)
                        if isinstance(widget, Gtk.Label) and widget.get_visible()
                        and widget.get_label() == 'Scale']
        verify("scale-title-not-wrapped-or-truncated", all(
            widget.get_layout().get_line_count() == 1 and not widget.get_layout().is_ellipsized()
            for widget in title_labels), visible_title_labels=len(title_labels))
        control_bounds = []
        percent = [widget for widget in descendants(window.scale_row)
                   if isinstance(widget, Gtk.Label) and widget.get_label() == '%']
        verify("scale-percent-unit-visible", len(percent) == 1 and percent[0].get_visible())
        for control in (window.slider, window.spin, percent[0]):
            success, rectangle = control.compute_bounds(window.scale_row)
            minimum, _natural, _baseline_min, _baseline_natural = control.measure(Gtk.Orientation.HORIZONTAL, -1)
            x, y = rectangle.get_x(), rectangle.get_y()
            width, height = rectangle.get_width(), rectangle.get_height()
            visible = (success and control.get_visible() and width >= minimum and height > 0
                       and x >= -0.5 and y >= -0.5
                       and x + width <= window.scale_row.get_width() + 0.5
                       and y + height <= window.scale_row.get_height() + 0.5)
            control_bounds.append(dict(type=type(control).__name__, visible=visible,
                x=x, y=y, width=width, height=height, minimum=minimum))
        verify("scale-controls-fully-visible", all(v['visible'] for v in control_bounds),
               row_width=window.scale_row.get_width(), row_height=window.scale_row.get_height(),
               controls=control_bounds)

        window.custom.set_active(True)
        until(lambda: store.get_profile(first.path)["override_enabled"] and window.session.state.inflight is None, "toggle autosave")
        verify("toggle-real-async-save", len(store.calls) >= 1 and all(item["thread"] != threading.get_ident() for item in store.calls))
        window.spin.set_text("165")
        until(lambda: store.get_profile(first.path)["ui_scale_percent"] == 165 and window.session.state.inflight is None, "typed autosave")
        verify("typed-autosave-saved-state", window.status_label.get_label() == "Saved" and window.spin.get_text() == "165")
        capture(window, "simple-saved")

        count = len(store.calls)
        window.spin.set_text("999")
        pump(0.8)
        verify("invalid-not-clamped-or-saved", window.spin.get_text() == "999" and len(store.calls) == count and store.get_profile(first.path)["ui_scale_percent"] == 165,
               visible=window.spin.get_text(), writes=len(store.calls) - count)
        verify("invalid-visible", window.session.state.value is None and "not saved" in window.status_label.get_label())
        verify("scan-blocked-during-unsaved-invalid-value", not window.scan_button.get_sensitive() and not window.add_button.get_sensitive())
        capture(window, "simple-invalid")
        window.spin.set_text("165")
        pump(0.1)
        window.spin.spin(Gtk.SpinType.STEP_FORWARD, 1)
        expected = round(window.adjustment.get_value())
        until(lambda: store.get_profile(first.path)["ui_scale_percent"] == expected and window.session.state.inflight is None, "plus autosave")
        verify("plus-increases-value", expected > 165, value=expected)
        window.spin.spin(Gtk.SpinType.STEP_BACKWARD, 1)
        until(lambda: store.get_profile(first.path)["ui_scale_percent"] == 165 and window.session.state.inflight is None, "minus autosave")
        window.slider.set_value(175)
        until(lambda: store.get_profile(first.path)["ui_scale_percent"] == 175 and window.session.state.inflight is None, "range autosave")
        verify("range-linked-to-spin", window.spin.get_text() == "175")

        selected = window.session
        window.search.set_text("2022")
        pump(0.25)
        window.filter_editors()
        pump(0.05)
        visible = []
        row = window.editor_list.get_first_child()
        while row:
            if row.get_visible() and row.get_child_visible():
                visible.extend(labels(row))
            row = row.get_next_sibling()
        verify("search-filters-actual-list", any("2022" in item for item in visible) and not any("6000.3" in item for item in visible), labels=visible)
        verify("filter-retains-active-session", window.session is selected and store.get_profile(first.path)["ui_scale_percent"] == 175)
        window.search.set_text("")
        pump(0.25)
        window.filter_editors()
        verify("cleared-filter-restores-selected-editor", window.session is selected and window.editor_list.get_selected_row() is window.rows[first.path] and window.controls.get_visible())
        window.select_editor(second.path)
        verify("independent-editor-default", window.spin.get_text() == "150" and not window.custom.get_active())
        window.select_editor(first.path)
        verify("selection-restores-saved-settings", window.spin.get_text() == "175" and window.custom.get_active())
        status = " ".join(labels(window)).lower()
        verify("unsupported-backend-truthful", ("unavailable" in status or "not available" in status or "not connected" in status or "incomplete" in status) and "applied successfully" not in status,
               status_label=window.status_label.get_label())
        window.custom.set_active(False)
        until(lambda: not store.get_profile(first.path)["override_enabled"] and window.session.state.inflight is None, "default toggle autosave")
        verify("default-keeps-custom-percent", store.get_profile(first.path)["ui_scale_percent"] == 175 and not window.scale_row.get_sensitive())
        window.custom.set_active(True)
        until(lambda: store.get_profile(first.path)["override_enabled"] and window.session.state.inflight is None, "restore custom toggle autosave")
        verify("custom-controls-enabled", window.scale_row.get_sensitive() and window.custom.get_active())
        capture(window, "simple-final")

        window.spin.set_text("180")
        window.close()
        verify("pending-close-offers-safe-choice", not window.closed and window.pending_dialog is not None)
        window.pending_dialog.response("save")
        until(lambda: window.closed and store.get_profile(first.path)["ui_scale_percent"] == 180, "close safely flushes pending valid edit")
        verify("close-pending-save-safe", window.closed and window.session.state.inflight is None)
        verify("other-editor-untouched", store.get_profile(second.path)["ui_scale_percent"] == 150 and not store.get_profile(second.path)["override_enabled"])
        completed = True
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if window is not None and not window.closed:
            window.force_close = True
            window.close()
            pump(0.1)
        (OUTPUT / "widgets.json").write_text(json.dumps({"checks": checks, "passed": completed and all(item["passed"] for item in checks),
            "limitations": "Software widget interactions and Cairo renders only; no physical input, installed Editor, Unity backend or KDE desktop validation"}, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
