#!/usr/bin/env python3
"""Host regression for native repaint-batch close lifetime; never launches Unity.

Compiles the actual production wrapper against synthetic view storage and
original-dispatch stubs. Checks cached and nested/direct paints, valid previews,
argument forwarding and balanced observer scopes. GPU presentation is covered
by separate disposable Unity acceptance, not this host fixture.
"""
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

p = Path(__file__).resolve().parent
flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libcrypto'], text=True))
with tempfile.TemporaryDirectory(prefix='unity-closed-batch-check-') as temporary:
    output = Path(temporary) / 'closed-batch-check'
    subprocess.run(['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-misleading-indentation', '-I' + str(p / 'source'),
        str(p / 'tests/closed_batch_paint.cpp'), *flags, '-ldl', '-pthread', '-o', str(output)], check=True)
    result = json.loads(subprocess.check_output([str(output)], text=True))
    if result['status'] != 'PASS' or result['scenarios'] != 4:
        raise RuntimeError('Closed-view batch dispatch regression failed')
print(json.dumps(result))
