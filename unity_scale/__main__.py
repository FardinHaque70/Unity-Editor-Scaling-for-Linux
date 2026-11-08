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
    from .user_install import install_user
    store = store or core.Store()
    source = Path(source or os.environ['APPIMAGE']).absolute()
    managed = store.data_dir / 'application.AppImage'
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
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            from . import updates
            updates.version_key(core.VERSION)
            from .native_backend import bundled_binaries
            bundled_binaries()
            for file in ('resources/update-public-key.pem', 'libexec/unity-scale-update-helper'):
                if not (core.ROOT / file).is_file():
                    raise core.AppError('Packaged component is missing: ' + file)
            print(json.dumps(dict(application=core.APP_NAME, version=core.VERSION, healthy=True)))
            return 0
        if args.post_update and not args.install_user:
            raise core.AppError('Post-update startup requires installation.')
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
