#!/usr/bin/env python3
"""Inert launcher/activation protocol fixtures, including relocation/refusal.

Only the test copy of activation.c substitutes the fixture ELF digest for the
immutable Unity digest. The shipped source/artifacts have no hash override.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'source'
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def identity(path):
    s=path.stat()
    return dict(st_dev=s.st_dev,st_ino=s.st_ino,st_size=s.st_size,st_mtime_ns=s.st_mtime_ns)
cases=[]
with tempfile.TemporaryDirectory(prefix='unity-launcher-fixtures-') as folder:
    root=Path(folder)
    editor=root/'Editor'
    package=editor/'.unity-editor-scaling'
    package.mkdir(parents=True,mode=0o700)
    original=editor/'.Unity.unity-scale-original'
    public=editor/'Unity'
    library=package/'native-v2.so'
    wrapper=package/'wrapper-v2'
    host=root/'host.c'
    host.write_text(r'''
#include <json-c/json.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char**argv){
 struct json_object*j=json_object_new_object(),*a=json_object_new_array();
 for(int i=0;i<argc;i++)json_object_array_add(a,json_object_new_string(argv[i]));
 json_object_object_add(j,"argv",a);
 const char*keys[]={"GDK_SCALE","GDK_DPI_SCALE","GDK_BACKEND","LD_PRELOAD"};
 for(unsigned i=0;i<4;i++){const char*v=getenv(keys[i]);json_object_object_add(j,keys[i],v?json_object_new_string(v):NULL);}
 puts(json_object_to_json_string_ext(j,JSON_C_TO_STRING_PLAIN));return 0;
}
''')
    subprocess.run(['cc',str(host),'-ljson-c','-o',str(original)],check=True)
    subprocess.run(['cc','-shared','-fPIC','-x','c','-o',str(library),'-'],input='void inert(void){}',text=True,check=True)
    # Test-only source copy replaces the production pinned SHA constant usage.
    fixture_source=root/'activation-fixture.c'
    fixture_source.write_text((SOURCE/'product/activation.c').read_text().replace('NSA_ORIGINAL_SHA',json.dumps(digest(original))))
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','json-c','libcrypto'],text=True))
    subprocess.run(['cc','-O2','-I'+str(HERE.parent),'-I'+str(SOURCE/'product'),str(HERE.parent/'launcher.c'),str(fixture_source),str(SOURCE/'product/product_policy.c'),*flags,'-lm','-o',str(wrapper)],check=True)
    shutil.copyfile(wrapper,public);public.chmod(0o700)
    activation=dict(schema=2,constructor_contract='product-profile-v2',public_editor=str(public),target_exe=str(original),settings=str(root/'settings.json'),wrapper='wrapper-v2',library='native-v2.so',owner_uid=os.getuid(),original_sha256=digest(original),library_sha256=digest(library),wrapper_sha256=digest(wrapper),original_identity=identity(original))
    descriptor=package/'activation.json'
    def write(value=None):
        descriptor.write_text(json.dumps(activation if value is None else value));descriptor.chmod(0o600)
    write()
    envelope=dict(abi=1,GDK_SCALE='2',GDK_DPI_SCALE='1.25',GDK_BACKEND='wayland')
    env={k:v for k,v in os.environ.items() if k!='LD_PRELOAD' and not k.startswith('UNITY_')}
    env.update(GDK_SCALE='1',GDK_DPI_SCALE='1',GDK_BACKEND='x11',UNITY_EDITOR_SCALING_HOST_ENV=json.dumps(envelope))
    def run(name,argv=('-batchMode',),success=True,changes=None):
        result=subprocess.run(['unchanged argv zero',*argv],executable=public,env=env|(changes or {}),text=True,capture_output=True)
        if success:
            assert result.returncode==0,(name,result.stderr)
            out=json.loads(result.stdout)
            assert out['argv']==['unchanged argv zero',*argv],(name,out)
            assert all(out[k]==v for k,v in envelope.items() if k!='abi'),(name,out)
        else: assert result.returncode==126 and 'left the Editor unstarted' in result.stderr,(name,result)
        cases.append(name)
    run('helper preserves argv0/all arguments and restores host',argv=('-batchMode','two words','--unrecognized=value',''))
    run('GUI launcher preserves argv/env with inert preload',argv=('-projectPath','two words'))
    for key,value in [('schema',1),('constructor_contract','product-profile-v1'),('public_editor','/elsewhere/Unity'),('target_exe','/bin/false'),('owner_uid',os.getuid()+1),('wrapper','../wrapper-v2'),('library_sha256','0'*64),('wrapper_sha256','0'*64),('settings','/tmp/../settings')]:
        write(activation|{key:value});run('reject '+key,success=False)
    write(activation|{'original_identity':identity(original)|{'st_ino':0}});run('reject original inode',success=False)
    write();descriptor.write_text(descriptor.read_text()[:-1]+',"schema":2}');run('reject duplicate JSON keys',success=False)
    write();descriptor.chmod(0o622);run('reject writable activation',success=False)
    write();package.chmod(0o755);run('reject nonprivate package',success=False);package.chmod(0o700)
    write();saved=root/'saved-library';library.rename(saved);library.symlink_to(saved);run('reject symlink library',success=False);library.unlink();saved.rename(library)
    write();public.write_bytes(public.read_bytes()+b'changed');run('reject changed public wrapper',success=False);shutil.copyfile(wrapper,public)
    write();original.write_bytes(original.read_bytes()+b'changed');run('reject changed original bytes/identity',success=False)
    # Relocation needs one new trusted activation and updated original inode:
    # the exact same generic launcher/library bytes are reused at the new path.
    original.write_bytes(original.read_bytes()[:-7]);original.chmod(0o700)
    moved=root/'relocated';shutil.copytree(editor,moved)
    public=moved/'Unity';original=moved/'.Unity.unity-scale-original';package=moved/'.unity-editor-scaling';descriptor=package/'activation.json'
    activation.update(public_editor=str(public),target_exe=str(original),original_identity=identity(original))
    write();run('same binaries relocate with a fresh trusted descriptor')
print(json.dumps(dict(launcher_activation_cases=cases,count=len(cases),Unity_run=False,test_only_digest_substitution=True)))
