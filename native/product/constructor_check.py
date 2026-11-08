#!/usr/bin/env python3
"""Exercise the actual constructor in a tiny disposable C host, never Unity.

Custom cannot pass the original-ELF hash in this host; this checks only safe
precommit refusal, neutral Default and helper/environment behavior.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--editor-source', required=True)
args = p.parse_args()
cases = []
with tempfile.TemporaryDirectory(prefix='unity-product-constructor-') as folder:
    root = Path(folder)
    target = root / 'Editor' / '.Unity.unity-scale-original'
    target.parent.mkdir()
    public = root / 'Editor' / 'Unity'
    public.write_text('Only a canonical settings key; never executed.\n')
    settings, library = root / 'settings.json', root / 'native.so'
    subprocess.run(['python3', str(HERE / 'build.py'), '--editor-source', args.editor_source,
                    '--target-exe', str(target), '--public-editor', str(public),
                    '--settings', str(settings), '--output', str(library)], check=True)
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
 puts(json_object_to_json_string_ext(j,JSON_C_TO_STRING_PLAIN));json_object_put(j);return 0;
}
''')
    subprocess.run(['cc', '-I' + str(HERE / 'source'), str(source), '-ljson-c', '-ldl', '-o', str(target)], check=True)
    foreign = root / 'foreign.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-x', 'c', '-o', str(foreign), '-'], input='void harmless(void){}', text=True, check=True)
    host = {'abi': 1, 'GDK_SCALE': '2', 'GDK_DPI_SCALE': '1.45', 'GDK_BACKEND': 'wayland'}
    base = os.environ.copy()
    for key in list(base):
        if key.startswith('UNITY_') or key == 'LD_PRELOAD':
            del base[key]
    base.update(LD_PRELOAD=str(library), GDK_SCALE='1', GDK_DPI_SCALE='1', GDK_BACKEND='x11',
                XDG_SESSION_TYPE='wayland', XDG_CURRENT_DESKTOP='KDE', DISPLAY=':0',
                UNITY_EDITOR_SCALING_HOST_ENV=json.dumps(host),
                UNITY_EDITOR_SCALING_SETTINGS=str(settings), UNITY_EDITOR_SCALING_PUBLIC_EDITOR=str(public),
                UNITY_EDITOR_SCALING_RECEIPT=str(root / 'receipt'))

    def run(name, enabled=True, argv=(), changes=None, expected=150, keep=False, error=None, malformed=False):
        settings.write_text('{' if malformed else json.dumps({'schema_version': 2, 'editors': {str(public): {
            'override_enabled': enabled, 'ui_scale_percent': 150, 'control_revision': 1}}, 'extra_editors': []}))
        env = base | (changes or {})
        result = subprocess.run([str(target), *argv], env=env, text=True, capture_output=True, check=True)
        value = json.loads(result.stdout)
        assert value['query_rc'] == 0 and value['installed'] == 0 and value['percent'] == expected, (name, value, result.stderr)
        expected_host = {k: v for k, v in host.items() if k != 'abi'}
        if changes and changes.get('UNITY_EDITOR_SCALING_HOST_ENV') == '{':
            expected_host = {'GDK_SCALE': '1', 'GDK_DPI_SCALE': '1', 'GDK_BACKEND': 'x11'}
        assert all(value[k] == v for k, v in expected_host.items()), (name, value)
        preload = value['LD_PRELOAD'] or ''
        assert (str(library) in preload) == keep, (name, value)
        if changes and str(foreign) in changes.get('LD_PRELOAD', ''):
            assert str(foreign) in preload, (name, value)
        if error:
            assert error in result.stderr, (name, result.stderr)
        cases.append(name)

    run('neutral Default restores host, retains neutral DSO', enabled=False, expected=0, keep=True)
    run('batch helper restores host, removes own DSO', argv=['-batchMode'], expected=0)
    run('Custom wrong ELF refuses before patching', error='ELF identity')
    run('unsupported session refuses', changes={'XDG_CURRENT_DESKTOP': 'GNOME'}, error='KDE Wayland')
    for flag in ['-force-vulkan', '-forceVulkan', '-force-gles', '-force-gles30', '-force-d3d9', '-force-d3d11', '-force-d3d12', '-force-metal', '-force-glcore33', '-force-glcore44']:
        run('unsupported renderer ' + flag, argv=[flag], error='unverified forced renderer')
    run('invalid profile refuses', malformed=True, expected=0, error='product profile refused')
    run('invalid host envelope refuses without guessing', changes={'UNITY_EDITOR_SCALING_HOST_ENV': '{'}, expected=0, error='host environment envelope refused')
    run('foreign preload Custom refuses and preserves foreign entry', changes={'LD_PRELOAD': str(foreign) + ':' + str(library)}, error='foreign preload')
    run('foreign preload Default retains both', enabled=False, changes={'LD_PRELOAD': str(foreign) + ':' + str(library)}, expected=0, keep=True)
    run('metadata redirect refuses', changes={'UNITY_EDITOR_SCALING_SETTINGS': str(root / 'elsewhere.json')}, expected=0, error='product profile refused')
print(json.dumps({'constructor_cases': cases, 'count': len(cases), 'Unity_run': False,
                  'limits': 'Tiny host deliberately fails the original Unity hash. No custom hook or GTK execution is tested.'}))
