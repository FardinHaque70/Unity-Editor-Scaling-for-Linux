"""Settings commands; native connection status is verified per Editor."""
import argparse
import json
import sys
from . import core


def bootstrap_appimage(*, store=None, source=None, installer=None, execute=None):
    """Install downloaded images once; opening an old download opens the managed app."""
    import os
    from pathlib import Path
    from . import updates
    from .native_backend import digest
    from .user_install import install_user, recover_install
    store = store or core.Store()
    recovery = updates.recover_interrupted_update(store=store)
    if recovery.get('state') == 'active':
        raise core.AppError('An application update is still in progress. Please wait for it to finish.')
    source = Path(source or os.environ['APPIMAGE']).absolute()
    managed = store.data_dir / 'application.AppImage'
    if recover_install(store) and managed.exists():
        (execute or os.execve)(str(managed), [str(managed), 'gui'], updates.host_environment())
        return
    if managed.exists() and source.samefile(managed):
        return
    if managed.exists():
        try:
            receipt = json.loads((store.state_dir / 'installation.json').read_text())
            installed = updates.version_key(receipt['version'])
            if receipt['image'] != str(managed) or receipt['image_sha256'] != digest(managed):
                raise ValueError('image receipt does not match')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise core.AppError('The managed installation needs repair. Open the installed app, or run this AppImage with --install-user to repair it.') from exc
        if installed >= updates.version_key(core.VERSION):
            (execute or os.execve)(str(managed), [str(managed), 'gui'], updates.host_environment())
            return
    (installer or install_user)(source, store=store)


def packaged_self_test():
    """Exercise shipped runtime dependencies without display, network or installation.

    The RFC 8032 vector checks the *shipped executable's* Ed25519 verifier; it
    never replaces the pinned production key used by the update path.
    """
    import base64
    import tempfile
    from pathlib import Path
    from . import updates
    from .native_backend import bundled_binaries
    updates.version_key(core.VERSION)
    bundled_binaries()
    for file in ('resources/update-public-key.pem', 'libexec/unity-scale-update-helper'):
        if not (core.ROOT / file).is_file():
            raise core.AppError('Packaged component is missing: ' + file)
    try:
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        gi.require_version('GdkPixbuf', '2.0')
        gi.require_version('Graphene', '1.0')
        from gi.repository import Adw, GdkPixbuf, Gio, GLib, Graphene, Gtk, Pango
        import cairo
        # Version access, GObject/GI marshaling, SVG loader and Cairo all run
        # without Gtk.init(), so this also works in bare distribution containers.
        gtk = [Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()]
        adw = [Adw.get_major_version(), Adw.get_minor_version(), Adw.get_micro_version()]
        if gtk < [4, 12, 0] or adw < [1, 4, 0]:
            raise core.AppError('The bundled GTK or libadwaita version is too old.')
        assert hasattr(Adw, 'ToolbarView') and hasattr(Gtk, 'FileDialog')
        rectangle = Graphene.Rect().init(0, 0, 12, 8)
        if rectangle.get_width() != 12:
            raise core.AppError('Graphene introspection did not load correctly.')
        font = Pango.FontDescription.from_string('Sans 12')
        if font.get_size() != 12 * Pango.SCALE:
            raise core.AppError('Pango introspection did not load correctly.')
        loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
        loader.write(b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="red"/></svg>')
        loader.close()
        if loader.get_pixbuf().get_width() != 8:
            raise core.AppError('The bundled SVG icon loader failed.')
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
        cairo.Context(surface).paint()
        if len(surface.get_data()) != 256:
            raise core.AppError('The bundled Cairo binding failed.')
        schemas = Gio.SettingsSchemaSource.get_default()
        if schemas is None or schemas.lookup('org.gtk.Settings.FileChooser', True) is None:
            raise core.AppError('The bundled GTK settings schemas are missing.')
        # Import the actual application classes too; no Gtk.Application is run.
        from .gui import UnityScaleApplication, UnityScaleWindow
        if not issubclass(UnityScaleWindow, Adw.ApplicationWindow):
            raise core.AppError('The packaged application could not be imported.')
    except Exception as exc:
        raise core.AppError('The bundled GUI runtime failed its check: ' + str(exc)) from exc
    public = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
    signature = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f'
                              'b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
    with tempfile.TemporaryDirectory(prefix='unity-scale-self-test-') as directory:
        key = Path(directory) / 'vector-public.pem'
        der = bytes.fromhex('302a300506032b6570032100') + public
        key.write_text('-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(der).decode() +
                       '\n-----END PUBLIC KEY-----\n')
        updates.verify_signature(b'', signature, public_key=key)
        try:
            updates.verify_signature(b'changed', signature, public_key=key)
        except updates.UpdateError:
            pass
        else:
            raise core.AppError('The packaged signature verifier accepted modified data.')
    return dict(application=core.APP_NAME, version=core.VERSION, healthy=True,
                gtk=gtk, libadwaita=adw, svg=True, cairo=True, signed_verifier=True,
                display_opened=False, installation_changed=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=core.APP_NAME)
    parser.add_argument('--version', action='version', version=core.VERSION)
    parser.add_argument('--install-user', action='store_true', help='Install this AppImage for the current user')
    parser.add_argument('--self-test', action='store_true', help='Check the packaged application without opening a window')
    parser.add_argument('--post-update', nargs=2, metavar=('ACK', 'TOKEN'), help=argparse.SUPPRESS)
    parser.add_argument('--recover-update', action='store_true', help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('gui', help='Open the settings app')
    configure = sub.add_parser('configure', help='Save an Editor preference')
    configure.add_argument('--editor', required=True)
    choice = configure.add_mutually_exclusive_group(required=True)
    choice.add_argument('--scale', type=int)
    choice.add_argument('--unity-default', action='store_true')
    status = sub.add_parser('status', help='Show saved preferences and backend availability')
    status.add_argument('--editor', required=True)
    restore = sub.add_parser('restore', help='Restore the original Unity Editor executable')
    restore.add_argument('--editor', required=True)
    sub.add_parser('uninstall', help='Restore connected Editors and remove the managed app; keep preferences')
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            print(json.dumps(packaged_self_test()))
            return 0
        if args.post_update and not args.install_user:
            raise core.AppError('Post-update startup requires installation.')
        if args.command == 'restore':
            from .native_backend import restore as restore_editor
            print(json.dumps(restore_editor(args.editor), indent=2))
            return 0
        if args.command == 'uninstall':
            from .user_install import uninstall_user
            print(json.dumps(uninstall_user(), indent=2))
            return 0
        if args.install_user:
            import os
            from pathlib import Path
            from .user_install import install_user
            image = os.environ.get('APPIMAGE')
            if not image:
                raise core.AppError('User installation requires running the AppImage.')
            result = install_user(Path(image))
            if not args.post_update and not args.recover_update:
                print(json.dumps(result, indent=2))
                return 0
        if args.command in (None, 'gui'):
            import os
            if os.environ.get('APPIMAGE') and not args.install_user:
                try:
                    bootstrap_appimage()
                except (core.AppError, OSError, ValueError) as exc:
                    from .gui import show_startup_error
                    return show_startup_error(exc)
            from .gui import main as gui_main
            return gui_main([], post_update=args.post_update)
        editor = core.inspect_editor(args.editor)
        store = core.Store()
        profile = store.get_profile(editor.path)
        if args.command == 'configure':
            profile['override_enabled'] = not args.unity_default
            if args.scale is not None:
                profile['ui_scale_percent'] = args.scale
            from .private_store import profile as checked_profile
            profile = checked_profile(profile)
            if profile['override_enabled']:
                from .native_backend import ensure_connected
                ensure_connected(editor.path, store)
            profile = store.set_profile(editor.path, profile)
        from .native_backend import status as backend_status
        backend = backend_status(editor.path, profile, settings_path=store.path)
        result = dict(editor=editor.path, version=editor.version,
                      saved=dict(override_enabled=profile['override_enabled'],
                                 ui_scale_percent=profile['ui_scale_percent']),
                      native_backend_available=backend['connected'], current_scale=None,
                      launcher_modified=backend['connected'], desktop_scale_modified=False,
                      live_apply=False, restart_required=backend['restart_required'],
                      backend_message=backend['message'])
        print(json.dumps(result, indent=2))
        return 0
    except (core.AppError, OSError, ValueError) as exc:
        print(core.APP_NAME + ': ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
