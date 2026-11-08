#!/usr/bin/python3
"""Artifact inspection only; no installation or Unity launch."""
from pathlib import Path
import os,subprocess,sys,tempfile
image=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='unity-artifact-audit-') as tmp:
 subprocess.run([str(image),'--appimage-extract'],cwd=tmp,check=True,stdout=subprocess.DEVNULL)
 root=Path(tmp)/'squashfs-root';app=root/'usr/share/unity-editor-scaling'
 for p in root.rglob('*'):
  if p.name in ('Unity','Unity_s.debug') or p.suffix in ('.o','.a','.pyc') or p.name=='__pycache__':raise SystemExit('Unexpected build/private artifact: '+str(p))
 for name in ('native-v2.so','wrapper-v2'):
  p=app/'native/prebuilt'/name
  out=subprocess.check_output(['readelf','-d',str(p)],text=True)
  if 'libcrypto.so' in out or 'libjson-c.so' in out:raise SystemExit('Native private dependencies must be static')
  if b'/home/fardin' in p.read_bytes():raise SystemExit('Machine-specific native path')
 print('Artifact verified:',image.stat().st_size,'bytes; no Unity binaries, objects or compiler dependencies.')
