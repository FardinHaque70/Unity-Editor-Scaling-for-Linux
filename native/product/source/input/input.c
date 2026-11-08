#include "input.h"
#include "v6_epoch_bridge.h"
#include <string.h>
#include <stdlib.h>
static uintptr_t image;
static double factor(void){ep_snapshot s;if(v6_conversion_snapshot(&s)||s.mode!=EP_CUSTOM||s.u<1||s.u>2)abort();return s.u;}
static double coord(const void*e,unsigned o){double x;memcpy(&x,(const char*)e+o,8);return x;}
static void press(void*event,void*frame){
 const double u=factor();float local[4]={(float)(coord(event,24)/u),(float)(coord(event,32)/u),0,0};
 float root[2]={(float)(coord(event,64)/u),(float)(coord(event,72)/u)};
 memcpy((char*)frame+0x30,local,8);memcpy((char*)frame+0x40,local,16);memcpy((char*)frame+0x28,root,8);
}
static __uint128_t release(void*event){
 const double u=factor();float local[2]={(float)(coord(event,24)/u),(float)(coord(event,32)/u)};
 void*(*get_drag)(void)=(void*(*)(void))(image+0x3bc4dd0);
 unsigned char(*dragging)(void*)=(unsigned char(*)(void*))(image+0x3bc5020);
 unsigned drag=dragging(get_drag());uint64_t bits;memcpy(&bits,local,8);return ((__uint128_t)drag<<64)|bits;
}
typedef struct{const char*name;uintptr_t va;size_t len;unsigned char before[160];} Original;
static const Original guards[]={
#include "guards.generated.h"
};
static const struct{uintptr_t va;size_t n;unsigned char before[192];} contexts[]={
#include "input-contexts.generated.h"
};
int ns_input_prepare(uintptr_t base,vg_patch out[2]){
 if(image||!base||!out)return -1;
 // Keep original stack cleanup and exact drag function calling conventions.
 const unsigned char cleanup[]={0x48,0x83,0xc4,0x10};
 if(memcmp((void*)(base+0x3c00d00),cleanup,sizeof cleanup))return -2;
 for(unsigned i=0;i<sizeof(contexts)/sizeof(*contexts);i++)
  if(memcmp((void*)(base+contexts[i].va),contexts[i].before,contexts[i].n))return -2;
 for(unsigned i=0;i<2;i++){
  const Original*g=&guards[i];if(g->len>sizeof(out[i].before)||memcmp((void*)(base+g->va),g->before,g->len))return -2;
  vg_patch*p=out+i;*p=(vg_patch){.name=g->name,.va=g->va,.len=g->len};memcpy(p->before,g->before,g->len);memset(p->after,0x90,g->len);
  const unsigned char a[]={0x48,0x89,0xdf,0x48,0x89,0xe6},b[]={0x48,0x89,0xef};size_t n=i?sizeof b:sizeof a;memcpy(p->after,i?b:a,n);
  void*fn=i?(void*)release:(void*)press;p->after[n++]=0x48;p->after[n++]=0xb8;memcpy(p->after+n,&fn,8);n+=8;p->after[n++]=0xff;p->after[n++]=0xd0;
  if(i){const unsigned char result[]={0x89,0xd5,0x66,0x48,0x0f,0x6e,0xc0,0x66,0x0f,0xd6,0x44,0x24,0x18};memcpy(p->after+n,result,sizeof result);n+=sizeof result;}
  if(n>g->len)return -3;
 }
 image=base;return 0;
}
