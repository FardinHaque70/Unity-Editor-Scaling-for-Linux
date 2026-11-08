#include "geometry.h"
#include "main_geometry/main.h"
#include "v6_epoch_bridge.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <xmmintrin.h>
static vg_host gtk;
static int bound;
int vg_bind(const vg_host*h){
 if(bound||!h||!h->gtk_scale||!h->resize||!h->move||!h->fixed_move||!h->size_request)return -1;
 gtk=*h;bound=1;return 0;
}
static ep_snapshot operation(void){
 ep_snapshot s;
 if(!bound||v6_conversion_snapshot(&s))abort();
 if(s.mode!=EP_DEFAULT&&(s.mode!=EP_CUSTOM||!isfinite(s.u)||s.u<=0))abort();
 return s;
}
static int stock(float f){return _mm_cvtt_ss2si(_mm_set_ss(f));}
static int q(double p,double u){
 double l=p*u;if(!isfinite(l)||l<INT32_MIN||l>INT32_MAX)abort();return(int)lround(l);
}
static int stock_policy(const ep_snapshot*s){return s->mode==EP_DEFAULT||s->u==1.0;}
void vg_container_request(void*w,const vg_rect*r,uintptr_t source){
 const ep_snapshot s=operation();int x,y,a,b;
 if(s.mode==EP_CUSTOM&&gtk.gtk_scale(w)!=1)abort();
 if(stock_policy(&s)){x=stock(r->x);y=stock(r->y);a=stock(r->w);b=stock(r->h);}
 else{x=q(r->x,s.u);y=q(r->y,s.u);a=q(r->w,s.u);b=q(r->h,s.u);}
 /* No second snapshot between two GTK calls. Never multiply default G. */
 mp_adjust_request(w,source,&s,&a,&b);
 gtk.resize(w,a,b);gtk.move(w,x,y);
}
void vg_child_request(void*fixed,void*child,const vg_rect*r){
 const ep_snapshot s=operation();int x,y,a,b;
 if(s.mode==EP_CUSTOM&&(gtk.gtk_scale(fixed)!=1||gtk.gtk_scale(child)!=1))abort();
 if(stock_policy(&s)){x=stock(r->x);y=stock(r->y);a=stock(r->w);b=stock(r->h);}
 else{
  x=q(r->x,s.u);y=q(r->y,s.u);
  if(r->w<0)a=stock(r->w);else {int64_t span=(int64_t)q((double)r->x+r->w,s.u)-(int64_t)x;if(span<INT32_MIN||span>INT32_MAX)abort();a=(int)span;}
  if(r->h<0)b=stock(r->h);else {int64_t span=(int64_t)q((double)r->y+r->h,s.u)-(int64_t)y;if(span<INT32_MIN||span>INT32_MAX)abort();b=(int)span;}
 }
 gtk.fixed_move(fixed,child,x,y);gtk.size_request(child,a,b);
}
int vg_accepted_changed(void*c,const vg_rect*next,unsigned equality_mask){
 const ep_snapshot s=operation();
 if(!stock_policy(&s))return(equality_mask&12)!=12;
 vg_rect old;memcpy(&old,(char*)c+0x30,sizeof old);
 /* Default/custom100 preserve original CVTTSS2SI accepted decision, including
  * INT_MIN sentinel behavior for nonfinite/out-of-range operands. */
 return stock(old.w)!=stock(next->w)||stock(old.h)!=stock(next->h);
}
static const vg_patch guards[4]={
#include "guards.h"
};
static void call(unsigned char*p,size_t*n,void*fn){p[(*n)++]=0x48;p[(*n)++]=0xb8;memcpy(p+*n,&fn,8);*n+=8;p[(*n)++]=0xff;p[(*n)++]=0xd0;}
static void branch(vg_patch*b,size_t*n,unsigned opcode,uintptr_t target){
 intptr_t d=(intptr_t)target-(intptr_t)(b->va+*n+2);if(d< -128||d>127)abort();b->after[(*n)++]=(unsigned char)opcode;b->after[(*n)++]=(unsigned char)d;
}
size_t vg_patches(vg_patch out[4]){
 if(!out)return 0;
 memcpy(out,guards,sizeof guards);
 for(unsigned i=0;i<4;i++){
  vg_patch*b=&out[i];memset(b->after,0x90,b->len);size_t n=0;
  if(i<2){
   const unsigned char top[]={0x49,0x8b,0xbe,0xa8,0,0,0,0x48,0x89,0xe6,0x48,0x89,0xda};
   const unsigned char child[]={0x49,0x8b,0x76,0x10,0x48,0x89,0xda};
   n=i?sizeof(child):sizeof(top);memcpy(b->after,i?child:top,n);
   call(b->after,&n,i?(void*)vg_child_request:(void*)vg_container_request);
  }else{
   const unsigned char onrect[]={0x0f,0x11,0x14,0x24,0x48,0x89,0xdf,0x48,0x89,0xe6,0x89,0xc2};
   const unsigned char configure[]={0x0f,0x11,0x54,0x24,0x10,0x4c,0x89,0xf7,0x48,0x8d,0x74,0x24,0x10,0x89,0xc2};
   n=i==2?sizeof(onrect):sizeof(configure);memcpy(b->after,i==2?onrect:configure,n);call(b->after,&n,vg_accepted_changed);
   const unsigned char restore_onrect[]={0x0f,0x10,0x14,0x24,0x0f,0x11,0x53,0x30,0x85,0xc0};
   const unsigned char restore_configure[]={0x0f,0x10,0x54,0x24,0x10,0x41,0x0f,0x11,0x56,0x30,0x85,0xc0};
   size_t k=i==2?sizeof(restore_onrect):sizeof(restore_configure);memcpy(b->after+n,i==2?restore_onrect:restore_configure,k);n+=k;
   branch(b,&n,0x74,i==2?0x3bf97fd:0x3bf9adb);
   branch(b,&n,0xeb,i==2?0x3bf9807:0x3bf9acc);
  }
  if(n>b->len)abort();
 }
 return 4;
}
