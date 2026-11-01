# Unity Scale beta development contract

Product: GTK4 + libadwaita standalone application for KDE Wayland. Editor-centric, no mandatory project picker. App name Unity Scale; Python package unity_scale; application id io.github.unityscale.UnityScale; version 0.1.0-beta.1. This is unofficial and does not redistribute Unity.

Settings keyed by canonical Editor executable, not project. No scripts, settings or logs written into projects. Existing working audit launcher must remain unchanged. Fixed bridge prototype-v5.2 source/binary retained; all geometry/cursor fixes preserved. Default UI scale150%.

Source tree: unity_scale/core.py model/config/discovery/preflight, unity_scale/runner.py child bridge/editor lifecycle, unity_scale/integration.py reversible editor launch integration, unity_scale/gui.py GTK GUI, unity_scale/__main__.py CLI entry. bin/unity-scale executable Python entry, resources/ icons and desktop files, packaging/ installers/build recipes, tests/.

Core GUI interface (root implements core.py):
- APP_ID, APP_NAME, VERSION constants; AppError(Exception).
- Editor dataclass(path: str, version: str, label: str, source: str), .to_dict(). discover_editors(extra_paths: list[str]|None=None)->list[Editor]; inspect_editor(path:str)->Editor (accepts executable/folder).
- Store() uses XDG_CONFIG_HOME/unity-scale/settings.json, state XDG_STATE_HOME/unity-scale, data XDG_DATA_HOME/unity-scale; .load()->dict, .save(dict), .get_profile(editor_path)->dict, .set_profile(editor_path, dict); profile defaults {ui_scale_percent:150, follow_desktop:false, render_scale:2}. .add_editor(path), .remove_editor(path).
- environment_status()->dict {supported:bool, desktop:str, session:str, desktop_scale_percent:float|None, checks:list[dict(name,ok,detail)], summary:str}. Do not block GTK loop: GUI calls slow functions on background worker.
- helper_path()->Path bundled libexec/xwayland-satellite (env UNITY_SCALE_HELPER optional).
- launch_command(editor_path:str, project:str|None=None, extra_args:list[str]|None=None)->list[str] invokes detached CLI runner. User argument vector preserved; no shell.

GUI implements UnityScaleApplication(Adw.Application); main(argv=None)->int. Main Editor list/profile selection,150/160 presets + scale numeric spin, desktop follow, Save settings (no closing running Unity), Locate Editor, Launch Editor (optional open-project action separate), per-editor integration status/control, diagnostics/about with beta scope. Use native Adwaita styling, no webviews. GUI must not require project selection. Changes apply next Editor launch. No forced terminate/restart of user Editor.

Runner: CLI accepts `python3 -m unity_scale run --editor /path/Editor/Unity [--project /path] [--dry-run] [-- extra Unity argv]`. No project required; passes all original Hub args unchanged. Read profile by original Editor path. run_editor(editor_path,project=None,extra_args=None,dry_run=False,...) optional real executable override for integration. Use exact v5.2 env/geometry and cursor config, x11 only for Unity child; app remains Wayland. Logs outside projects; per-project lock same runtime as existing launcher when project known; no session kill. Headless/-version invocations bypass bridge.

Integration investigation is pending; GUI should support toggle once backend final. root coordinates API. Do not mutate live Unity installation before isolated fake-Editor integration tests.

Packaging: user-local install and uninstall, no sudo default; self-contained source/payload release tar with Python GTK dependencies documented, build-from-source bridge path; packaged native helper local glibc2.43 clearly labeled until portable build is verified. Preserve MPL source+LICENSE+credits. CI build/test scripts and source release are useful; do not publish externally. Tests must verify actual argument forwarding, clean shutdown, config and install reversibility.
