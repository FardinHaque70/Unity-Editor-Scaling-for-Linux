#!/usr/bin/env python3
"""Create self-contained source and local-native release archives, never upload."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from unity_scale.core import VERSION, APP_SLUG


def selected(path:Path,include_binary:bool):
    relative=path.relative_to(ROOT)
    if any(p in {'dist','.git','__pycache__','.venv','target'} for p in relative.parts):return False
    if path.suffix in {'.pyc','.pyo'}:return False
    if relative.as_posix()=='libexec/xwayland-satellite' and not include_binary:return False
    return path.is_file()


def build(label='linux-x86_64-glibc2.43'):
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    records=[]
    for kind,binary in [('source',False),(label,True)]:
        if binary and not (ROOT/'libexec/xwayland-satellite').is_file():continue
        name=f'{APP_SLUG}-{VERSION}-{kind}.tar.gz';output=dist/name
        prefix=f'{APP_SLUG}-{VERSION}'
        with tarfile.open(output,'w:gz') as archive:
            for p in sorted(ROOT.rglob('*')):
                if selected(p,binary):archive.add(p,arcname=f'{prefix}/{p.relative_to(ROOT)}',recursive=False)
        digest=hashlib.sha256(output.read_bytes()).hexdigest()
        records.append({'file':name,'sha256':digest,'bytes':output.stat().st_size})
        print(f'{name}: {output.stat().st_size}bytes')
    source = next(r for r in records if r['file'].endswith('-source.tar.gz'))
    arch = dist/'arch';arch.mkdir(exist_ok=True)
    template=(ROOT/'packaging/arch/PKGBUILD.in').read_text()
    (arch/'PKGBUILD').write_text(template.replace('@SOURCE_SHA256@',source['sha256']))
    (dist/'SHA256SUMS').write_text(''.join(f"{r['sha256']}  {r['file']}\n" for r in records))
    (dist/'release.json').write_text(json.dumps({'version':VERSION,'platform_label':label,'published':False,'artifacts':records},indent=2)+'\n')
    return records

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--label',default='linux-x86_64-glibc2.43')
    build(parser.parse_args().label)
