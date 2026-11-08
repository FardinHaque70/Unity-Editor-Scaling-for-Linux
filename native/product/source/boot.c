#define _GNU_SOURCE
#include "v6_native.h"
#include "startup.h"
#include "product/host_environment.h"
#include "product/environment.h"
#include "input/input.h"
#include <setjmp.h>
#include "deps/integration.h"
#include "deps/native_scope_guard.h"
#include "review/scopes.h"
#include "geometry/prepare.h"
#include "main_geometry/main.h"
#include "geometry/extras.h"
#include <dlfcn.h>
#include <link.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <dirent.h>
#include "product/activation.h"
#include "rendering/render_boundary.h"
#include "rb-addresses.generated.h"
#include "guards.generated.h"
typedef struct{unsigned off,end;uintptr_t target;} ep_gpu_fix;
typedef struct{const char*name;uintptr_t va;size_t n;unsigned char bytes[160];unsigned fixes;ep_gpu_fix fix[8];} ep_gpu_recipe;
#include "gpu-recipes.generated.h"
extern uint64_t ep_actual_pixels(void*);
extern void *ep_backing_viewport(void*);
extern void ep_backing_screen(void*,void*);
static uintptr_t image;
static v6g_plan precise_geometry;
static mp_plan main_geometry;
static vg_patch input_patches[2];
static jmp_buf rejection;
static int committed;
static const char *mapped_library;
static void die(const char *s){dprintf(2,"Unity scaling %s: %s\n",committed?"installation failed":"disabled",s);if(!committed){ns_refused(s);if(mapped_library&&nsp_strip_own_preload(mapped_library))dprintf(2,"Unity scaling: owned preload removal failed; no scaling installed.\n");longjmp(rejection,1);}_exit(126);}
static int locate(struct dl_phdr_info *i,size_t n,void *p){(void)n;(void)p;if(!i->dlpi_name||!i->dlpi_name[0])image=i->dlpi_addr;return 0;}
static void jump(void *to,void *target){unsigned char p[14]={0xff,0x25,0,0,0,0};memcpy(p+6,&target,8);memcpy(to,p,14);}
static void page(uintptr_t va,size_t len,int prot){uintptr_t a=(image+va)&~(uintptr_t)4095,b=(image+va+len+4095)&~(uintptr_t)4095;if(mprotect((void*)a,b-a,prot))die("code protection");}
static void hash_guard(void){
 const nsa_config *config=nsa_current();struct stat running,target,public;
 if(stat("/proc/self/exe",&running)||lstat(config->target_exe,&target)||
    !S_ISREG(target.st_mode)||running.st_dev!=target.st_dev||running.st_ino!=target.st_ino)
  die("running ELF differs from validated original path");
 if(lstat(config->public_editor,&public)||(running.st_dev==public.st_dev&&running.st_ino==public.st_ino))
  die("public launcher is not the allowed original ELF target");
 if(nsa_hash(config->target_exe,NSA_ORIGINAL_SHA))die("ELF identity");
}
static void *near_page(uintptr_t va){
 uintptr_t anchor=(image+va)&~(uintptr_t)4095;
 for(uintptr_t d=0x10000;d<0x70000000;d+=0x10000){uintptr_t a[2]={anchor+d,anchor>d?anchor-d:0};for(int i=0;i<2;i++){if(a[i]<0x10000)continue;void *p=mmap((void*)a[i],4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);if(p!=MAP_FAILED)return p;}}
 return NULL;
}
static void *retain_scope(const v6_scope_candidate *s){
 if(s->displaced<14||s->displaced>32||s->reloc_count>2||memcmp((void*)(image+s->va),s->before,s->displaced))die("scope original bytes");
 unsigned char *p=near_page(s->va);if(!p)die("scope near allocation");memcpy(p,s->before,s->displaced);jump(p+s->displaced,(void*)(image+s->va+s->displaced));size_t island=s->displaced+14;
 for(unsigned i=0;i<s->reloc_count;i++){
  v6_scope_reloc r=s->reloc[i];if(r.offset+r.width>s->displaced)die("scope relocation range");
  uintptr_t target=(r.target>=s->va&&r.target<s->va+s->displaced)?(uintptr_t)p+r.target-s->va:image+r.target;
  if(r.width==1){jump(p+island,(void*)target);target=(uintptr_t)p+island;island+=14;}
  int64_t d=(int64_t)target-(int64_t)((uintptr_t)p+r.end);
  if(r.width==1){if(d<INT8_MIN||d>INT8_MAX)die("scope rel8");int8_t n=d;memcpy(p+r.offset,&n,1);}
  else {if(r.width!=4||d<INT32_MIN||d>INT32_MAX)die("scope rel32");int32_t n=d;memcpy(p+r.offset,&n,4);}
 }
 if(mprotect(p,4096,PROT_READ|PROT_EXEC))die("scope RX");return p;
}
static void *(*menu_create)(void);
static void *h_menubar(void){ns_before_menu();void *w=menu_create();ns_menubar(w);return w;}
int ns_log_open(const char*base,char*out,size_t size){return nsp_open_receipt(base,out,size);}
__attribute__((constructor))static void init(void){
 Dl_info own_library;if(dladdr((void*)init,&own_library))mapped_library=own_library.dli_fname;
 /* Inherited custom GDK state must be undone even for helpers, foreign
  * processes, Default or a later policy/ELF refusal. No GTK call before this. */
 int host_rc=ups_restore_host_env_json(getenv(UPS_HOST_ENV_KEY));
 nsa_config activation;int paths_rc=nsa_paths(mapped_library,0,&activation);
 struct usg_result scope=usg_current_scope(paths_rc?"/__unity_scaling_invalid_package__":activation.target_exe);
 if(scope.scope==USG_FOREIGN||scope.scope==USG_BYPASS){
  if(host_rc!=UPS_OK&&(scope.scope==USG_BYPASS||getenv(UPS_HOST_ENV_KEY)))dprintf(2,"Unity scaling: host environment restoration refused (%d); bypassed without scaling.\n",host_rc);
  if(mapped_library&&nsp_strip_own_preload(mapped_library))dprintf(2,"Unity scaling: owned preload removal failed; bypassed without scaling.\n");
  return;
 }
 if(setjmp(rejection))return;
 if(host_rc!=UPS_OK)die("host environment envelope refused; no scaling installed");
 if(scope.scope!=USG_GUI_CANDIDATE)die(scope.reason);
 if(paths_rc||nsa_validate(&activation))die("runtime activation refused");
 nsa_use(&activation);
 if(sysconf(_SC_PAGESIZE)!=4096)die("page size");
 int mode=ns_initialize();ns_bootstrap(0);
 if(mode<0)die("authoritative product profile refused");
 if(!mode)return; /* Keep only the neutral loader for fresh OpenProject reread. */
 int session=nsp_custom_session();
 if(session==-1)die("custom scaling currently supports KDE Wayland with a valid DISPLAY only");
 if(session)die("custom scaling session could not be verified");
 if(!mapped_library||nsp_has_foreign_preload(mapped_library)!=0)die("custom scaling with foreign preload is unsupported");
 DIR *tasks=opendir("/proc/self/task");if(!tasks)die("thread inventory");unsigned thread_count=0;struct dirent *de;while((de=readdir(tasks)))if(de->d_name[0]!='.')++thread_count;closedir(tasks);if(thread_count!=1)die("requires pristine single-threaded launch");
 hash_guard();dl_iterate_phdr(locate,NULL);if(!image)die("PIE base");
 for(size_t i=0;i<sizeof(semantic_guards)/sizeof(*semantic_guards);i++)if(memcmp((void*)(image+semantic_guards[i].va),semantic_guards[i].before,16))die("native semantic query guard");
 if(ep_wrapper_bind_gtk(image))die("raw GTK symbols");
 menu_create=dlsym(RTLD_DEFAULT,"gtk_menu_bar_new");if(!menu_create)die("gtk_menu_bar_new");
 if(ep_make_originals(image))die("retain originals");
 if(ep_make_gpu_originals(image))die("retain GPU original/custom islands");
 if(ns_input_prepare(image,input_patches))die("button float boundary guards");
 for(size_t i=0;i<4;i++)if(memcmp((void*)(image+gpu_recipes[i].va),gpu_recipes[i].bytes,gpu_recipes[i].n))die("full GPU original block");
 size_t ns=0;const v6_scope_candidate *scopes=v6_scope_candidates(&ns);if(ns!=8)die("scope count");
 int use_scope[8];for(size_t i=0;i<ns;i++){use_scope[i]=1;for(size_t j=0;j<sizeof(rb_addresses)/sizeof(*rb_addresses);j++)if(scopes[i].va==rb_addresses[j])use_scope[i]=0;}
 void *originals[8];for(size_t i=0;i<ns;i++)originals[i]=retain_scope(&scopes[i]);
 size_t nc=ep_wrapper_count();const struct ep_candidate *c=ep_wrapper_candidates();const ep_gpu_recipe *g=gpu_recipes;
 for(size_t i=0;i<ns;i++)for(size_t j=0;j<nc;j++)if(scopes[i].va<=c[j].va+13&&c[j].va<=scopes[i].va+13)die("overlapping scope/wrapper");
 size_t ne=0;const v6_scope_candidate *extras=v6_extras_candidates(&ne);if(ne!=2||v6_extras_bind(image))die("precise origin symbols");
 void *extra_originals[2];for(size_t i=0;i<ne;i++)extra_originals[i]=retain_scope(&extras[i]);
 v6g_range ranges[100];size_t nr=0;
 for(size_t i=0;i<nc;i++)ranges[nr++]=(v6g_range){c[i].name,c[i].va,14};
 for(size_t i=0;i<4;i++)ranges[nr++]=(v6g_range){g[i].name,g[i].va,g[i].n};
 for(size_t i=0;i<2;i++)ranges[nr++]=(v6g_range){input_patches[i].name,input_patches[i].va,input_patches[i].len};
 for(size_t i=0;i<ns;i++)if(use_scope[i])ranges[nr++]=(v6g_range){scopes[i].name,scopes[i].va,scopes[i].displaced};
 for(size_t i=0;i<ne;i++)ranges[nr++]=(v6g_range){extras[i].name,extras[i].va,extras[i].displaced};
 for(size_t i=0;i<sizeof(rb_addresses)/sizeof(*rb_addresses);i++)ranges[nr++]=(v6g_range){"RB",rb_addresses[i],16};
 ranges[nr++]=(v6g_range){"menu_factory",0x3c06440,14};
 vg_host raw={(int(*)(void*))dlsym(RTLD_DEFAULT,"gtk_widget_get_scale_factor"),(void(*)(void*,int,int))dlsym(RTLD_DEFAULT,"gtk_window_resize"),(void(*)(void*,int,int))dlsym(RTLD_DEFAULT,"gtk_window_move"),(void(*)(void*,void*,int,int))dlsym(RTLD_DEFAULT,"gtk_fixed_move"),(void(*)(void*,int,int))dlsym(RTLD_DEFAULT,"gtk_widget_set_size_request")};
 if(v6g_prepare(image,&raw,ranges,nr,&precise_geometry))die("precise geometry guard/overlap");
 for(size_t i=0;i<ne;i++)*extras[i].original=extra_originals[i];
 if(mp_prepare(image,&main_geometry))die("main producer original guards");
 /* RB container_allocate displaced/written prefix is exactly7bytes, verified
  * by frozen entry_guards and mp_prepare context. Body tail starts at+7. */
 for(size_t i=0;i<main_geometry.count;i++)for(size_t j=0;j<nr;j++){
   size_t len=ranges[j].len;if(ranges[j].va==0x3bf9e60&&!strcmp(ranges[j].name,"RB"))len=7;
   uintptr_t a=main_geometry.patches[i].va,b=ranges[j].va;
   if(a<b+len&&b<a+main_geometry.patches[i].len)die("main producer overlap");
 }
 v6_scope_callbacks callbacks={0};if(v6_scope_attach_callbacks(&callbacks))die("scope callbacks");
 ns_bootstrap(image);
 if(rb_install_launch_only(image))die(rb_last_error());
 committed=1; /* RB installation has committed; later OS write/protection failure cannot safely continue. */
 const struct ep_gpu_candidate *routes=ep_gpu_candidates();
 /* All verification/allocation/original publication precede first code write.
  * Fresh process constructor only; no active instance installation is provided. */
 for(size_t i=0;i<ns;i++)*scopes[i].original=originals[i];
 for(size_t i=0;i<nc;i++)page(c[i].va,14,PROT_READ|PROT_WRITE|PROT_EXEC);
 for(size_t i=0;i<4;i++)page(g[i].va,g[i].n,PROT_READ|PROT_WRITE|PROT_EXEC);
 for(size_t i=0;i<ns;i++)if(use_scope[i])page(scopes[i].va,14,PROT_READ|PROT_WRITE|PROT_EXEC);
 page(0x3c06440,14,PROT_READ|PROT_WRITE|PROT_EXEC);
 for(size_t i=0;i<main_geometry.count;i++)page(main_geometry.patches[i].va,main_geometry.patches[i].len,PROT_READ|PROT_WRITE|PROT_EXEC);
 for(size_t i=0;i<2;i++)page(input_patches[i].va,input_patches[i].len,PROT_READ|PROT_WRITE|PROT_EXEC);
 for(size_t i=0;i<ne;i++)page(extras[i].va,14,PROT_READ|PROT_WRITE|PROT_EXEC);
 for(size_t i=0;i<precise_geometry.count;i++)page(precise_geometry.patches[i].va,precise_geometry.patches[i].len,PROT_READ|PROT_WRITE|PROT_EXEC);
 for(size_t i=0;i<nc;i++)jump((void*)(image+c[i].va),c[i].replacement);
 for(size_t i=0;i<4;i++)jump((void*)(image+g[i].va),routes[i].replacement);
 for(size_t i=0;i<2;i++)memcpy((void*)(image+input_patches[i].va),input_patches[i].after,input_patches[i].len);
 for(size_t i=0;i<ns;i++)if(use_scope[i])jump((void*)(image+scopes[i].va),scopes[i].replacement);
 jump((void*)(image+0x3c06440),h_menubar);
 for(size_t i=0;i<main_geometry.count;i++)memcpy((void*)(image+main_geometry.patches[i].va),main_geometry.patches[i].after,main_geometry.patches[i].len);
 for(size_t i=0;i<ne;i++)jump((void*)(image+extras[i].va),extras[i].replacement);
 for(size_t i=0;i<precise_geometry.count;i++)memcpy((void*)(image+precise_geometry.patches[i].va),precise_geometry.patches[i].after,precise_geometry.patches[i].len);
 for(size_t i=0;i<nc;i++)page(c[i].va,14,PROT_READ|PROT_EXEC);
 for(size_t i=0;i<4;i++)page(g[i].va,g[i].n,PROT_READ|PROT_EXEC);
 for(size_t i=0;i<ns;i++)if(use_scope[i])page(scopes[i].va,14,PROT_READ|PROT_EXEC);
 page(0x3c06440,14,PROT_READ|PROT_EXEC);
 for(size_t i=0;i<main_geometry.count;i++)page(main_geometry.patches[i].va,main_geometry.patches[i].len,PROT_READ|PROT_EXEC);
 for(size_t i=0;i<2;i++)page(input_patches[i].va,input_patches[i].len,PROT_READ|PROT_EXEC);
 for(size_t i=0;i<ne;i++)page(extras[i].va,14,PROT_READ|PROT_EXEC);
 for(size_t i=0;i<precise_geometry.count;i++)page(precise_geometry.patches[i].va,precise_geometry.patches[i].len,PROT_READ|PROT_EXEC);if(mp_mark_installed())die("main producer installation readback");ns_installed();
}
