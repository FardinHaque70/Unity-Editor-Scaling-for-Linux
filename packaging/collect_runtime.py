#!/usr/bin/env python3
"""Collect GUI ELF dependencies and audit the bundled GI dependency closure.

Never copy GPU drivers, glibc or native GTK3 backend dependencies. GI can load
libraries absent from GTK's ELF dependency tree, so typelib shared-library
metadata is an additional dependency root. No host typelib fallback is allowed.
"""
from pathlib import Path
import ctypes
import json
import re
import shutil
import subprocess
import sys

EXCLUDE = re.compile(r'^(ld-linux|lib(c|m|dl|pthread|rt|resolv|util|anl)\.so|lib(GL|EGL|GLX|GLdispatch|OpenGL|vulkan|nvidia|cuda))')


def elf(path):
    try:
        with path.open('rb') as stream:
            return stream.read(4) == b'\x7fELF'
    except OSError:
        return False


def typelib_closure(root):
    directory = root / 'usr/lib/girepository-1.0'
    library = root / 'usr/lib/libgirepository-1.0.so.1'
    if not library.is_file():
        raise RuntimeError('Bundled GIRepository library missing')
    gi = ctypes.CDLL(str(library))
    gi.g_irepository_get_default.restype = ctypes.c_void_p
    gi.g_irepository_prepend_search_path.argtypes = [ctypes.c_char_p]
    gi.g_irepository_require.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
    gi.g_irepository_require.restype = ctypes.c_void_p
    gi.g_irepository_get_immediate_dependencies.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    gi.g_irepository_get_immediate_dependencies.restype = ctypes.POINTER(ctypes.c_char_p)
    for function in ('g_irepository_get_typelib_path', 'g_irepository_get_shared_library'):
        getattr(gi, function).argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        getattr(gi, function).restype = ctypes.c_char_p
    gi.g_irepository_prepend_search_path(str(directory).encode())
    repository = gi.g_irepository_get_default()
    pending = [('Gtk', '4.0'), ('Adw', '1')]
    records = {}
    while pending:
        name, version = pending.pop()
        key = name + '-' + version
        if key in records:
            continue
        if not gi.g_irepository_require(repository, name.encode(), version.encode(), 0, None):
            raise RuntimeError('Cannot load required typelib dependency: ' + key)
        path = Path(gi.g_irepository_get_typelib_path(repository, name.encode()).decode()).resolve()
        expected = directory / (key + '.typelib')
        if path != expected.resolve() or not expected.is_file():
            raise RuntimeError('Required typelib resolved outside AppDir: ' + key + ' (' + str(path) + ')')
        dependency_array = gi.g_irepository_get_immediate_dependencies(repository, name.encode())
        dependencies = []
        index = 0
        if dependency_array:
            while dependency_array[index]:
                dependency = dependency_array[index].decode()
                dependencies.append(dependency)
                namespace, required_version = dependency.rsplit('-', 1)
                pending.append((namespace, required_version))
                index += 1
        raw = gi.g_irepository_get_shared_library(repository, name.encode())
        shared = raw.decode().split(',') if raw else []
        records[key] = dict(path=str(expected.relative_to(root)), dependencies=dependencies, shared_libraries=shared)
    return records


def system_libraries():
    result = {}
    output = subprocess.check_output(['/sbin/ldconfig', '-p'], text=True)
    for line in output.splitlines():
        found = re.search(r'^\s*(\S+)\s+\([^)]*x86-64[^)]*\)\s+=>\s+(\S+)', line)
        if found:
            result.setdefault(found[1], Path(found[2]))
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit('Usage: collect_runtime.py APPDIR')
    root = Path(argv[0]).resolve()
    library_dir = root / 'usr/lib'
    library_dir.mkdir(exist_ok=True, parents=True)
    typelibs = typelib_closure(root)
    host_libraries = system_libraries()
    copied = []
    queue = [path for path in root.rglob('*') if path.is_file() and '/native/' not in str(path) and elf(path)]
    for name in sorted({name for record in typelibs.values() for name in record['shared_libraries']}):
        if '/' in name:
            raise RuntimeError('Nonrelocatable typelib library name: ' + name)
        target = library_dir / name
        if not target.is_file():
            if name not in host_libraries or EXCLUDE.match(name):
                raise RuntimeError('Unresolved typelib shared library: ' + name)
            shutil.copy2(host_libraries[name].resolve(), target)
            copied.append(name)
        queue.append(target)
    seen = set()
    while queue:
        path = queue.pop()
        if str(path) in seen:
            continue
        seen.add(str(path))
        output = subprocess.run(['ldd', str(path)], text=True, capture_output=True).stdout
        for line in output.splitlines():
            if '=> not found' in line:
                raise RuntimeError('Unresolved runtime dependency: ' + str(path) + ': ' + line)
            found = re.search(r'=> (/\S+)', line)
            if not found:
                continue
            source = Path(found[1])
            name = source.name
            if EXCLUDE.match(name):
                continue
            target = library_dir / name
            if not target.exists():
                shutil.copy2(source.resolve(), target)
                copied.append(name)
            queue.append(target)
    report = root / 'usr/share/unity-editor-scaling/resources/runtime-dependencies.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(dict(schema=1, typelibs=typelibs, copied_libraries=sorted(copied)), indent=2, sort_keys=True) + '\n')
    print('Collected GUI runtime libraries:', len(copied), '; verified bundled typelibs:', len(typelibs))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
