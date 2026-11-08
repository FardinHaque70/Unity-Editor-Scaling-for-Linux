#!/usr/bin/env python3
"""Real GObject signal/lifetime check with a fake native repaint callee; no UI."""
from pathlib import Path
import shlex
import subprocess

p = Path(__file__).resolve().parent
out = p / 'build' / 'accepted-repaint-check'
out.parent.mkdir(exist_ok=True)
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gobject-2.0'], text=True))
subprocess.run(['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-DNSP_REPAINT_TESTING',
                '-I' + str(p / 'tests'), '-I' + str(p / 'source'), str(p / 'tests/accepted_repaint.cpp'),
                str(p / 'source/rendering/accepted_repaint.cpp'), '-pthread', *flags, '-o', str(out)], check=True)
result = subprocess.check_output([str(out)], text=True)
(p / 'build' / 'accepted-repaint-check.json').write_text(result)
print(result, end='')
