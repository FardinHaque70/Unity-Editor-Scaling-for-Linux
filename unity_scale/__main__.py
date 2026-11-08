"""Settings commands; native connection status is verified per Editor."""
import argparse
import json
import sys
from . import core


def main(argv=None):
    parser = argparse.ArgumentParser(description=core.APP_NAME)
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
        if args.command in (None, 'gui'):
            from .gui import main as gui_main
            return gui_main([])
        editor = core.inspect_editor(args.editor)
        store = core.Store()
        profile = store.get_profile(editor.path)
        if args.command == 'configure':
            profile['override_enabled'] = not args.unity_default
            if args.scale is not None:
                profile['ui_scale_percent'] = args.scale
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
