#!/usr/bin/env python3
"""Exercise shipped constructor refusal/bypass in a tiny C host; never Unity."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--editor-source', help='Optional exact ELF read-only verification')
p.add_argument('--library', type=Path, help='Use actual prebuilt artifact instead of rebuilding')
args = p.parse_args()
cases = []
with tempfile.TemporaryDirectory(prefix='unity-product-constructor-') as folder:
    root = Path(folder)
    editor = root / 'Editor'
    package = editor / '.unity-editor-scaling'
    package.mkdir(parents=True, mode=0o700)
    target = editor / '.Unity.unity-scale-original'
    library = package / 'native-v2.so'
    if args.library:
        shutil.copyfile(args.library, library)
    else:
        command = ['python3', str(HERE / 'build.py'), '--output', str(library)]
        if args.editor_source:
            command += ['--editor-source', args.editor_source]
        subprocess.run(command, check=True)
    source = root / 'host.c'
    source.write_text(r'''
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <json-c/json.h>
#include "startup.h"
int main(void){
 struct json_object*j=json_object_new_object();
 const char*keys[]={"GDK_SCALE","GDK_DPI_SCALE","GDK_BACKEND","LD_PRELOAD"};
 for(unsigned i=0;i<4;i++){const char*v=getenv(keys[i]);json_object_object_add(j,keys[i],v?json_object_new_string(v):NULL);}
 ns_status s={0};int(*query)(ns_status*,uint32_t)=dlsym(RTLD_DEFAULT,"unity_native_startup_query");
 int rc=query?query(&s,sizeof s):-99;
 json_object_object_add(j,"query_rc",json_object_new_int(rc));
 json_object_object_add(j,"percent",json_object_new_int(s.percent));
 json_object_object_add(j,"installed",json_object_new_int(s.installed));
 ns_settled_snapshot settled={0};int(*snapshot)(ns_settled_snapshot*,uint32_t)=dlsym(RTLD_DEFAULT,"unity_native_settled_query");
 json_object_object_add(j,"settled_rc",json_object_new_int(snapshot?snapshot(&settled,sizeof settled):-99));
 json_object_object_add(j,"settled_views",json_object_new_int(settled.view_count));
 puts(json_object_to_json_string_ext(j,JSON_C_TO_STRING_PLAIN));json_object_put(j);return 0;
}
''')
    subprocess.run(['cc', '-I' + str(HERE / 'source'), str(source), '-ljson-c', '-ldl', '-o', str(target)], check=True)
    foreign = root / 'foreign.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-x', 'c', '-o', str(foreign), '-'], input='void harmless(void){}', text=True, check=True)
    host = {'abi': 1, 'GDK_SCALE': '2', 'GDK_DPI_SCALE': '1.45', 'GDK_BACKEND': 'wayland'}
    base = {k:v for k,v in os.environ.items() if not k.startswith('UNITY_') and k != 'LD_PRELOAD'}
    base.update(LD_PRELOAD=str(library), GDK_SCALE='1', GDK_DPI_SCALE='1', GDK_BACKEND='x11',
                UNITY_EDITOR_SCALING_HOST_ENV=json.dumps(host))
    def run(name, argv=(), changes=None, error=None, executable=None):
        env = base | (changes or {})
        result = subprocess.run([str(executable or target), *argv], env=env, text=True, capture_output=True, check=True)
        value = json.loads(result.stdout)
        assert value['query_rc'] == 0 and value['installed'] == 0 and value['percent'] == 0, (name, value, result.stderr)
        assert value['settled_rc'] == -2 and value['settled_views'] == 0, (name,value)
        expected_host = {k:v for k,v in host.items() if k != 'abi'}
        if changes and changes.get('UNITY_EDITOR_SCALING_HOST_ENV') == '{':
            expected_host = {'GDK_SCALE':'1','GDK_DPI_SCALE':'1','GDK_BACKEND':'x11'}
        assert all(value[k] == v for k,v in expected_host.items()), (name,value)
        assert str(library) not in (value['LD_PRELOAD'] or ''), (name,value)
        if changes and str(foreign) in changes.get('LD_PRELOAD',''):
            assert str(foreign) in (value['LD_PRELOAD'] or ''), (name,value)
        if error: assert error in result.stderr, (name,result.stderr)
        cases.append(name)
    for flag in ['-batchMode','-nographics','-version','--version','-help','--help','-returnlicense','-manuallicensefile','-createmanualactivationfile']:
        run('helper restores host and removes preload: '+flag, argv=[flag])
    run('LightBakerWorker bypass',argv=['-name','LightBakerWorker17'])
    run('missing activation refuses before policy/patch',error='runtime activation refused')
    (package/'activation.json').write_text('{')
    run('malformed activation refuses before policy/patch',error='runtime activation refused')
    run('invalid host envelope refuses before activation',changes={'UNITY_EDITOR_SCALING_HOST_ENV':'{'},error='host environment envelope refused')
    run('foreign preload preserved on refusal',changes={'LD_PRELOAD':str(foreign)+':'+str(library)},error='runtime activation refused')
    other = root/'foreign-host'
    shutil.copyfile(target,other);other.chmod(0o700)
    run('foreign executable restores host before invalid activation',executable=other)
print(json.dumps({'constructor_cases':cases,'count':len(cases),'Unity_run':False,
                  'limits':'Actual artifact in inert host. Successful Unity Custom hooks and GTK execution are not tested.'}))
