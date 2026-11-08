#include "main.h"
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
static uintptr_t image;
static int prepared,installed;
static mp_plan plan;
static _Thread_local unsigned depth;
static ep_snapshot operation(void){ep_snapshot s;if(v6_conversion_snapshot(&s))abort();return s;}
static int custom(const ep_snapshot*s){return s->mode==EP_CUSTOM&&isfinite(s->u)&&s->u>=1&&s->u<=2;}
static int read_main(uint64_t native,const ep_snapshot*s,cg_sample*out){
 return custom(s)&&native&&native==v6_main_handle()&&!v6_main_read(native,(float)s->u,out);
}
static vg_rect points(const cg_sample*s){vg_rect r;memcpy(&r,s->target_container_points,sizeof r);return r;}
vg_rect mp_menu_rect(void*c,const int*slots){
 const ep_snapshot s=operation();
 vg_rect r={(float)slots[4],(float)slots[3],(float)slots[2],(float)slots[1]-(float)slots[0]};
 cg_sample actual;if(read_main((uint64_t)(uintptr_t)c,&s,&actual)){r=points(&actual);v6_main_trace(1,&actual,depth);}
 return r;
}
void mp_configure_rect(void*c,float*wh,int y,float*xy){
 const ep_snapshot s=operation();
 float w=fmaxf(1,wh[0]),h=fmaxf(1,wh[1]-(float)y);cg_sample actual;
 if(read_main((uint64_t)(uintptr_t)c,&s,&actual)){
  vg_rect r=points(&actual);w=r.w;h=r.h;xy[0]=r.x;xy[1]=r.y;v6_main_trace(2,&actual,depth);
 }
 wh[0]=w;wh[1]=h;
}
void mp_adjust_request(void*top,uintptr_t source,const ep_snapshot*s,int*w,int*h){
 (void)w;if(!custom(s))return;
 uint64_t native=v6_main_handle();if(!native)return;
 void*widget;memcpy(&widget,(void*)(uintptr_t)(native+0xa8),sizeof widget);
 if(widget!=top)return;
 /* Exact native OnStateChange passes saved WHOLE client Rect by this address.
  * All other audited callers pass accepted-content dimensions. Keep global
  * saved/raw/preference chart untouched; never infer by numeric coincidence. */
 if(source==image+0x60566d0)return;
 int menu;if(v6_main_menu_height(native,&menu)||menu<1)abort();
 int64_t full=(int64_t)*h+menu;if(full<1||full>INT_MAX)abort();
 *h=(int)full;
 cg_sample actual;if(!v6_main_read(native,(float)s->u,&actual))v6_main_trace(4,&actual,depth);
}
void mp_allocated_tail(void*allocation,void*c){
 /* Original retained RB prefix has already executed RDI=allocation. Body
  * replacement takes RSI=RBXcontainer; existing POP/RET remain after helper. */
 (void)((cg_rect(*)(void*))(image+0x3c03050))(allocation);
 unsigned char*p=((unsigned char*(*)(void*))(image+0x3b32550))(c);p[0x2e]=1;
 const ep_snapshot s=operation();cg_sample actual;
 if(!read_main((uint64_t)(uintptr_t)c,&s,&actual))return;
 vg_rect r=points(&actual);depth++;v6_main_trace(3,&actual,depth);
 ((void(*)(void*,vg_rect))(image+0x3bf9790))(c,r);
 /* Managed OnResize can destroy/reparent c. No native/object read after it. */
 depth--;
}
static const vg_patch expected[3]={
#include "patches.generated.h"
};
typedef struct{uintptr_t va;size_t len;unsigned char before[512];} Context;
static const Context contexts[]={
#include "contexts.generated.h"
};
static void call(unsigned char*p,size_t*n,void*fn){p[(*n)++]=0x48;p[(*n)++]=0xb8;memcpy(p+*n,&fn,8);*n+=8;p[(*n)++]=0xff;p[(*n)++]=0xd0;}
int mp_prepare(uintptr_t base,mp_plan*out){
 if(!base||!out||prepared)return -1;
 mp_plan next={0};next.count=3;memcpy(next.patches,expected,sizeof expected);
 for(unsigned i=0;i<3;i++)if(memcmp((void*)(base+expected[i].va),expected[i].before,expected[i].len))return -2;
 for(unsigned i=0;i<sizeof(contexts)/sizeof(*contexts);i++)if(memcmp((void*)(base+contexts[i].va),contexts[i].before,contexts[i].len))return -2;
 for(unsigned i=0;i<3;i++){
  vg_patch*b=&next.patches[i];memset(b->after,0x90,b->len);size_t n=0;
  const unsigned char menu[]={0x4c,0x89,0xff,0x48,0x89,0xe6};
  const unsigned char configure[]={0x4c,0x89,0xf7,0x48,0x8d,0x74,0x24,0x10,0x89,0xda,0x48,0x8d,0x4c,0x24,0x50};
  const unsigned char allocated[]={0x48,0x89,0xde};
  n=i==0?sizeof menu:i==1?sizeof configure:sizeof allocated;
  memcpy(b->after,i==0?menu:i==1?configure:allocated,n);
  call(b->after,&n,i==0?(void*)mp_menu_rect:i==1?(void*)mp_configure_rect:(void*)mp_allocated_tail);
  if(n>b->len)return -3;
 }
 image=base;plan=next;prepared=1;*out=next;return 0;
}
int mp_mark_installed(void){
 if(!prepared||installed)return -1;
 for(unsigned i=0;i<3;i++)if(memcmp((void*)(image+plan.patches[i].va),plan.patches[i].after,plan.patches[i].len))return -1;
 vg_patch geometry[4];if(vg_patches(geometry)!=4)return -1;
 for(unsigned i=0;i<4;i++)if(memcmp((void*)(image+geometry[i].va),geometry[i].after,geometry[i].len))return -1;
 installed=1;return 0;
}
int mp_validate_target(const cg_sample*s,float from_u){
 if(!s||s->mode!=4||!installed||(!isfinite(from_u)||from_u<1||from_u>2))return -1;
 for(unsigned i=0;i<3;i++)if(memcmp((void*)(image+plan.patches[i].va),plan.patches[i].after,plan.patches[i].len))return -1;
 vg_patch geometry[4];if(vg_patches(geometry)!=4)return -1;
 for(unsigned i=0;i<4;i++)if(memcmp((void*)(image+geometry[i].va),geometry[i].after,geometry[i].len))return -1;
 cg_sample target,source;
 if(v6_main_read(s->native,s->target_u,&target)||v6_main_read(s->native,from_u,&source))return -1;
 if(memcmp(&s->top_position_size_L,&target.top_position_size_L,sizeof(cg_rect))||
    memcmp(&s->content_L,&target.content_L,sizeof(cg_rect))||
    memcmp(s->target_container_points,target.target_container_points,16)||
    memcmp(source.cached_points,source.target_container_points,16))return -1;
 return 0;
}
