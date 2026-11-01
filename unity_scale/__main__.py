"""GTK application and automation entry points."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

from .core import APP_NAME, VERSION, AppError, Store, diagnostics, discover_editors


def _parser():
    parser = argparse.ArgumentParser(prog="unity-scale", description="Editor-wide Unity scaling for KDE Wayland. Run without arguments for the GTK app.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="Launch a selected Editor with its saved scale, preserving Unity arguments")
    run.add_argument("--editor", required=True)
    run.add_argument("--real-executable", help=argparse.SUPPRESS)
    run.add_argument("--project", help="Optional project to open; settings remain Editor-wide")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("unity_args", nargs=argparse.REMAINDER)
    sub.add_parser("editors", help="List detected Editors as JSON")
    diagnostic = sub.add_parser("diagnostics", help="Print a shareable compatibility report without project paths or raw logs")
    diagnostic.add_argument("--output", type=Path)
    for action in ("enable", "disable", "status"):
        cmd = sub.add_parser(action, help=f"{action.title()} Hub launch integration for one Editor")
        cmd.add_argument("--editor", required=True)
    config = sub.add_parser("configure", help="Save Editor-wide settings")
    config.add_argument("--editor", required=True)
    scale = config.add_mutually_exclusive_group(required=True)
    scale.add_argument("--scale", type=float)
    scale.add_argument("--follow-desktop", action="store_true")
    gui = sub.add_parser("gui", help="Open the GTK app")
    gui.add_argument("gui_args", nargs=argparse.REMAINDER)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Smoke mode is intentionally GUI-only and uses no real settings/integration.
    if not argv or argv[0] == "--smoke-test":
        try:
            from .gui import main as gui_main
            return gui_main(argv)
        except (ImportError, ValueError) as exc:
            print(f"{APP_NAME} needs GTK4, libadwaita and Python GObject bindings: {exc}", file=sys.stderr)
            return 1
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import main as gui_main
            return gui_main(args.gui_args)
        if args.command == "run":
            from .runner import run_editor
            extra = args.unity_args
            if extra[:1] == ["--"]:extra = extra[1:]
            return run_editor(args.editor, project=args.project, extra_args=extra, dry_run=args.dry_run, real_executable=args.real_executable)
        if args.command == "editors":
            print(json.dumps([e.to_dict() for e in discover_editors()], indent=2))
        elif args.command == "diagnostics":
            text = json.dumps(diagnostics(), indent=2) + "\n"
            if args.output:
                args.output.write_text(text)
                print(f"Saved diagnostics to {args.output}")
            else:print(text, end="")
        elif args.command == "configure":
            from .core import inspect_editor
            editor = inspect_editor(args.editor)
            store = Store()
            profile = store.get_profile(editor.path)
            profile["follow_desktop"] = bool(args.follow_desktop)
            if args.scale is not None:profile["ui_scale_percent"] = args.scale
            store.set_profile(editor.path, profile)
            print("Settings saved for this Editor. They apply to every project on its next scaled launch.")
        elif args.command in ("enable", "disable", "status"):
            from . import integration
            result = getattr(integration, args.command)(args.editor)
            print(json.dumps(result, indent=2))
        else:
            parser.print_help()
        return 0
    except (AppError, OSError, RuntimeError, ValueError) as exc:
        print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
