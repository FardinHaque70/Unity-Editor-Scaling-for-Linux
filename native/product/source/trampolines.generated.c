#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <sys/mman.h>
#include <limits.h>
/* Build retained ORIGINAL targets before root writes any entry patches.
 * Caller must independently verify loaded ELF hash/scope. This file never
 * changes a single byte in the target. One RX page per target, no RWX. */
typedef struct { unsigned off,width,end; uintptr_t target; int internal; } ep_fix;
typedef struct { const char *name; uintptr_t va; size_t n; unsigned char bytes[64]; unsigned fixes; ep_fix fix[4]; } ep_recipe;
#include "recipes.generated.h"
struct ep_candidate { const char *name; uintptr_t va; void *replacement; void **original; };
extern size_t ep_wrapper_count(void);
extern const struct ep_candidate *ep_wrapper_candidates(void);
static void jump(unsigned char *p,uintptr_t to) { const unsigned char op[6]={0xff,0x25,0,0,0,0}; memcpy(p,op,6);memcpy(p+6,&to,8); }
static void *near_page(uintptr_t target) {
 /* Exact-build x86_64 Linux4096 only. Bounded search, never MAP_FIXED. */
 uintptr_t anchor=target&~(uintptr_t)4095;
 for(uintptr_t distance=0x10000;distance<0x70000000;distance+=0x10000) {
  uintptr_t choices[2]={anchor+distance,anchor>distance?anchor-distance:0};
  for(int j=0;j<2;j++) {
   if(choices[j]<0x10000)continue;
   void *p=mmap((void*)choices[j],4096,PROT_READ|PROT_WRITE,
     MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
   if(p!=MAP_FAILED)return p;
  }
 }
 return NULL;
}
int ep_make_originals(uintptr_t image) {
 const struct ep_candidate *c=ep_wrapper_candidates();
 const size_t count=sizeof(recipes)/sizeof(recipes[0]);
 void *pages[31]={0};
 if(ep_wrapper_count()!=count)return -1;
 for(size_t i=0;i<count;i++) {
  const ep_recipe *r=&recipes[i];
  if(strcmp(c[i].name,r->name)||c[i].va!=r->va||*c[i].original||
     memcmp((void*)(image+r->va),r->bytes,r->n))goto fail;
  unsigned char *p=near_page(image+r->va);if(!p)goto fail;
  pages[i]=p;memcpy(p,r->bytes,r->n);jump(p+r->n,image+r->va+r->n);
  size_t island=r->n+14;
  for(unsigned j=0;j<r->fixes;j++) {
   ep_fix f=r->fix[j];uintptr_t to=f.internal?(uintptr_t)p+f.target-r->va:image+f.target;
   if(f.width==1&&!f.internal) { jump(p+island,to);to=(uintptr_t)p+island;island+=14; }
   int64_t delta=(int64_t)to-(int64_t)((uintptr_t)p+f.end);
   if(f.width==1) {if(delta<INT8_MIN||delta>INT8_MAX)goto fail;int8_t d=delta;memcpy(p+f.off,&d,1);}
   else {if(delta<INT32_MIN||delta>INT32_MAX)goto fail;int32_t d=delta;memcpy(p+f.off,&d,4);}
  }
  if(mprotect(p,4096,PROT_READ|PROT_EXEC))goto fail;
 }
 /* Publish only after ALL targets validated and sealed. Keep until process exit:
  * wrappers can outlive plugin/domain reload; never unmap on managed reload. */
 for(size_t i=0;i<count;i++)*c[i].original=pages[i];
 return 0;
fail:
 for(size_t i=0;i<count;i++)if(pages[i])munmap(pages[i],4096);
 return -1;
}
/* GPU block mode gates are permanent. Mode is selected from the same TLS
 * snapshot as geometry/input wrappers; original bytes never get repatched live. */
#include "v6_epoch_bridge.h"
typedef struct { unsigned off,end; uintptr_t target; } ep_gpu_fix;
typedef struct { const char *name; uintptr_t va; size_t n; unsigned char bytes[160]; unsigned fixes; ep_gpu_fix fix[8]; } ep_gpu_recipe;
#include "gpu-recipes.generated.h"
#define GPU(N) void *ep_gpu_stock_##N __attribute__((visibility("hidden"))); \
 void *ep_gpu_custom_##N __attribute__((visibility("hidden"))); extern void ep_gpu_gate_##N(void)
GPU(0);GPU(1);GPU(2);GPU(3);
extern uint64_t ep_actual_pixels(void*);
extern void *ep_backing_viewport(void*);
extern void ep_backing_screen(void*,void*);
int ep_gpu_custom_selector(void) { ep_snapshot s; if(v6_conversion_snapshot(&s))__builtin_trap();return s.mode==EP_CUSTOM; }
struct ep_gpu_candidate { uintptr_t va; size_t n; void *replacement; };
static struct ep_gpu_candidate gpu_candidates[4];
const struct ep_gpu_candidate *ep_gpu_candidates(void) {return gpu_candidates;}
int ep_make_gpu_originals(uintptr_t image) {
 void **stock[]={&ep_gpu_stock_0,&ep_gpu_stock_1,&ep_gpu_stock_2,&ep_gpu_stock_3};
 void **custom[]={&ep_gpu_custom_0,&ep_gpu_custom_1,&ep_gpu_custom_2,&ep_gpu_custom_3};
 void *gates[]={ep_gpu_gate_0,ep_gpu_gate_1,ep_gpu_gate_2,ep_gpu_gate_3};
 void *pages[4]={0};
 for(unsigned i=0;i<4;i++) {
  const ep_gpu_recipe *r=&gpu_recipes[i];
  if(*stock[i]||*custom[i]||memcmp((void*)(image+r->va),r->bytes,r->n))goto fail;
  unsigned char *p=near_page(image+r->va);if(!p)goto fail;pages[i]=p;
  memcpy(p,r->bytes,r->n);jump(p+r->n,image+r->va+r->n);
  for(unsigned j=0;j<r->fixes;j++) {
   ep_gpu_fix f=r->fix[j];int64_t delta=(int64_t)(image+f.target)-(int64_t)((uintptr_t)p+f.end);
   if(delta<INT32_MIN||delta>INT32_MAX)goto fail;
   int32_t d=delta;memcpy(p+f.off,&d,4);
  }
  /* Copy the audited V4 custom block payload to a second island, ending in
   * an absolute jump back. Its call uses the original caller stack alignment. */
  unsigned char *c=p+512;size_t n=0;void *fn;
  if(i==3) {const unsigned char args[]={0x4c,0x89,0xf7,0x48,0x89,0xde};memcpy(c,args,sizeof args);n=sizeof args;fn=ep_backing_screen;}
  else {const unsigned char args[]={0x48,0x89,0xdf};memcpy(c,args,sizeof args);n=sizeof args;fn=i==2?(void*)ep_backing_viewport:(void*)ep_actual_pixels;}
  c[n++]=0x48;c[n++]=0xb8;memcpy(c+n,&fn,8);n+=8;c[n++]=0xff;c[n++]=0xd0;
  if(i<2) {const unsigned char reshape[]={0x41,0x89,0xc6,0x48,0xc1,0xe8,0x20,0x41,0x89,0xc7};const unsigned char create[]={0x41,0x89,0xc7,0x48,0xc1,0xe8,0x20,0x41,0x89,0xc4};memcpy(c+n,i==0?reshape:create,sizeof reshape);n+=sizeof reshape;}
  else if(i==2) {const unsigned char result[]={0x48,0x89,0xc5};memcpy(c+n,result,sizeof result);n+=sizeof result;}
  jump(c+n,image+r->va+r->n);
  if(mprotect(p,4096,PROT_READ|PROT_EXEC))goto fail;
 }
 for(unsigned i=0;i<4;i++) { *stock[i]=pages[i];*custom[i]=(char*)pages[i]+512;gpu_candidates[i]=(struct ep_gpu_candidate){gpu_recipes[i].va,gpu_recipes[i].n,gates[i]}; }
 return 0;
fail:
 for(unsigned i=0;i<4;i++)if(pages[i])munmap(pages[i],4096);
 return -1;
}
