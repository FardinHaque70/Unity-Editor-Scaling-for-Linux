#!/usr/bin/env python3
"""Sign exact release manifest bytes; never print private key material."""
import hashlib,json,os,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];dist=root/'dist';name='Unity-Editor-Scaling-for-Linux-x86_64.AppImage';image=dist/name
version=os.environ['RELEASE_VERSION'].removeprefix('v')
manifest=dict(schema=1,version=version,channel='prerelease' if '-' in version else 'stable',architecture='x86_64',filename=name,size=image.stat().st_size,sha256=hashlib.sha256(image.read_bytes()).hexdigest())
p=dist/'release.json';p.write_text(json.dumps(manifest,sort_keys=True,separators=(',',':'))+'\n')
with tempfile.TemporaryDirectory(prefix='unity-sign-') as t:
 key=Path(t)/'key.pem';key.write_text(os.environ['RELEASE_SIGNING_KEY']);key.chmod(0o600)
 subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(p),'-out',str(dist/'release.json.sig')],check=True)
(dist/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n' for f in (image,p,dist/'release.json.sig')))
print('Signed release manifest for',version)
