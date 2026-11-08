#!/usr/bin/env python3
"""Check scaling-session safety and renderer-argument independence; no Unity."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='ues-renderer-admission-') as folder:
    root = Path(folder)
    source = root / 'host.c'
    source.write_text('#include <stdio.h>\n#include "product/environment.h"\n'
                      'int main(void){printf("%d\\n", nsp_custom_session());}\n')
    executable = root / 'host'
    subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', '-I' + str(HERE / 'source'),
                    str(source), str(HERE / 'source/product/environment.c'),
                    '-o', str(executable)], check=True)
    env = dict(os.environ, XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='KDE', DISPLAY=':0')
    cases = []
    def check(argv, expected, changes=None):
        actual = int(subprocess.check_output([str(executable), *argv], env=env | (changes or {}), text=True))
        assert actual == expected, (argv, changes, actual, expected)
        cases.append(dict(argv=argv, environment=changes or {}, result=actual))
    for argv in ([], ['-force-glcore'], ['-force-glcore45'], ['-force-vulkan'], ['-projectPath', '/tmp/test', '-force-vulkan']):
        check(argv, 0)
    for flag in ('-forceVulkan', '-force-gles', '-force-gles30', '-force-d3d9', '-force-d3d11',
                 '-force-d3d12', '-force-metal', '-force-glcore32', '-force-glcore33',
                 '-force-glcore40', '-force-glcore41', '-force-glcore42', '-force-glcore43',
                 '-force-glcore44', '-force-clamped'):
        check([flag], 0)
        check(['-force-vulkan', flag], 0)
    check(['-force-vulkan', '-FORCE-D3D12'], 0)
    for changes in ({'XDG_SESSION_TYPE': 'x11'}, {'XDG_CURRENT_DESKTOP': 'GNOME'}, {'DISPLAY': ''}):
        check(['-force-vulkan'], -1, changes)
    check(['-force-vulkan'], 0, {'XDG_CURRENT_DESKTOP': 'other:KDE'})
print(json.dumps(dict(session_renderer_cases=len(cases), cases=cases, Unity_run=False)))
