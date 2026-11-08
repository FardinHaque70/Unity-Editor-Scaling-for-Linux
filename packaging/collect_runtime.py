#!/usr/bin/env python3
"""Collect GUI ELF dependencies; never copy GPU drivers, glibc or native GTK3 backend dependencies."""
from pathlib import Path
import re,shutil,subprocess,sys
root=Path(sys.argv[1]).resolve();lib=root/'usr/lib';lib.mkdir(exist_ok=True,parents=True)
exclude=re.compile(r'^(ld-linux|lib(c|m|dl|pthread|rt|resolv|util|anl)\.so|lib(GL|EGL|GLX|GLdispatch|OpenGL|vulkan|nvidia|cuda))')
def elf(p):
 try:
  with p.open('rb') as f:return f.read(4)==b'\x7fELF'
 except OSError:return False
queue=[p for p in root.rglob('*') if p.is_file() and '/native/' not in str(p) and elf(p)]
seen=set();copied=[]
while queue:
 p=queue.pop()
 if str(p) in seen:continue
 seen.add(str(p))
 out=subprocess.run(['ldd',str(p)],text=True,capture_output=True).stdout
 for line in out.splitlines():
  if '=> not found' in line:raise SystemExit(f'Unresolved runtime dependency: {p}: {line}')
  m=re.search(r'=> (/\S+)',line)
  if not m:continue
  source=Path(m.group(1));name=source.name
  if exclude.match(name):continue
  target=lib/name
  if not target.exists():shutil.copy2(source.resolve(),target);copied.append(name)
  queue.append(target)
print('Collected GUI runtime libraries:',len(copied))
