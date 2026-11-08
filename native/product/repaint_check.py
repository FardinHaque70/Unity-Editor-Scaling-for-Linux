#!/usr/bin/env python3
"""Real GObject signal/lifetime check with a fake native repaint callee; no UI."""
from pathlib import Path
import shlex
import subprocess
import tempfile

p = Path(__file__).resolve().parent
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gobject-2.0'], text=True))
with tempfile.TemporaryDirectory(prefix='unity-repaint-check-') as temporary:
    out = Path(temporary) / 'accepted-repaint-check'
    subprocess.run(['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', '-DNSP_REPAINT_TESTING',
                    '-I' + str(p / 'tests'), '-I' + str(p / 'source'), str(p / 'tests/accepted_repaint.cpp'),
                    str(p / 'source/rendering/accepted_repaint.cpp'), '-pthread', *flags, '-o', str(out)], check=True)
    result = subprocess.check_output([str(out)], text=True)
print(result, end='')
