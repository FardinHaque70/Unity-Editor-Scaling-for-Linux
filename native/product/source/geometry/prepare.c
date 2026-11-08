#include "prepare.h"
#include <string.h>
#include <stdint.h>
#include "contexts.generated.h"
static int valid(uintptr_t a,size_t n){return n&&n<=UINTPTR_MAX-a;}
static int overlaps(uintptr_t a,size_t n,uintptr_t b,size_t m){return a<b+m&&b<a+n;}
int v6g_prepare(uintptr_t image,const vg_host*host,const v6g_range*existing,size_t count,v6g_plan*out){
 if(!image||!host||!out||!existing||!count||count>256||!host->gtk_scale||!host->resize||!host->move||!host->fixed_move||!host->size_request)return -1;
 v6g_plan plan={0};plan.count=vg_patches(plan.patches);if(plan.count!=4)return -1;
 for(size_t j=0;j<count;j++)if(!valid(existing[j].va,existing[j].len))return -2;
 for(unsigned i=0;i<4;i++){
  const vg_patch *p=&plan.patches[i];
  if(!valid(p->va,p->len)||p->len>sizeof(p->before)||p->va>UINTPTR_MAX-image||p->len>UINTPTR_MAX-(image+p->va))return -2;
  for(size_t j=0;j<count;j++)if(overlaps(p->va,p->len,existing[j].va,existing[j].len))return -2;
  for(unsigned j=0;j<i;j++)if(overlaps(p->va,p->len,plan.patches[j].va,plan.patches[j].len))return -2;
  if(memcmp((void*)(image+p->va),p->before,p->len))return -3;
 }
 for(unsigned i=0;i<sizeof(contexts)/sizeof(*contexts);i++){
  const uintptr_t a=contexts[i].va;const size_t n=contexts[i].n;
  if(a>UINTPTR_MAX-image||n>UINTPTR_MAX-(image+a))return -2;
  for(size_t j=0;j<count;j++)if(overlaps(a,n,existing[j].va,existing[j].len))return -2;
  if(memcmp((void*)(image+a),contexts[i].before,n))return -3;
 }
 /* Last step: binding mutates only helper-local pointers, never target bytes.
  * Every root allocator/preparer must finish before first target write. */
 if(vg_bind(host))return -4;
 *out=plan;return 0;
}
