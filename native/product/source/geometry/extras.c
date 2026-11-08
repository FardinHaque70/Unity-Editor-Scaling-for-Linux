#define _GNU_SOURCE
#include "extras.h"
#include "v6_epoch_bridge.h"
#include <dlfcn.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <math.h>
typedef struct{float x,y;} Vec;
typedef struct{float x,y,w,h;} Rect;
static uintptr_t image;
static void*(*get_parent)(void*);static void*(*get_window)(void*);
static int(*get_scale)(void*);static int(*origin)(void*,int*,int*);
static Vec*(*original_gui)(Vec*,void*);static Vec*(*original_top)(Vec*,void*);
static ep_snapshot snapshot(void){ep_snapshot s;if(v6_conversion_snapshot(&s))abort();return s;}
static void g1(void*w){if(w&&get_scale(w)!=1)abort();}
static Vec *h_gui(Vec*out,void*view){
 const ep_snapshot s=snapshot();if(s.mode==EP_DEFAULT)return original_gui(out,view);
 *out=(Vec){0,0};void*w=NULL;if(view)memcpy(&w,(char*)view+0x10,8);
 if(w){g1(w);int x=0,y=0;(void)origin(get_window(w),&x,&y);*out=(Vec){(float)(x/s.u),(float)(y/s.u)};}
 return out;
}
static Vec *h_top(Vec*out,void*container){
 const ep_snapshot s=snapshot();if(s.mode==EP_DEFAULT)return original_top(out,container);
 void*w;int mode;memcpy(&w,(char*)container+0xb0,8);memcpy(&mode,(char*)container+0x40,4);
 if(mode==4){w=get_parent(w);w=get_parent(w);}g1(w);
 int x=0,y=0;(void)origin(get_window(w),&x,&y);*out=(Vec){(float)(x/s.u),(float)(y/s.u)};return out;
}
static const v6_scope_candidate entries[]={
#include "extras.generated.h"
};
int v6_extras_bind(uintptr_t base){
 if(image||!base)return -1;
 *(void**)&get_parent=dlsym(RTLD_DEFAULT,"gtk_widget_get_parent");
 *(void**)&get_window=dlsym(RTLD_DEFAULT,"gtk_widget_get_window");
 *(void**)&get_scale=dlsym(RTLD_DEFAULT,"gtk_widget_get_scale_factor");
 *(void**)&origin=dlsym(RTLD_DEFAULT,"gdk_window_get_origin");
 if(!get_parent||!get_window||!get_scale||!origin)return -1;
 image=base;return 0;
}
const v6_scope_candidate *v6_extras_candidates(size_t*n){if(n)*n=2;return entries;}
static int q(float p,double u){double v=p*u;if(!isfinite(v)||v<INT32_MIN||v>INT32_MAX)abort();return(int)lround(v);}
void v6_precise_popup(void*menu,int*x,int*y,int*push,void*data){
 const ep_snapshot s=snapshot();
 typedef void(*Fn)(void*,int*,int*,int*,void*);Fn original=(Fn)(image+0x3bc3770);
 if(s.mode==EP_DEFAULT||s.u==1.0){original(menu,x,y,push,data);return;}
 Rect *r;memcpy(&r,(void*)(image+0x67af398),8);if(!r)abort();
 const float px=r->x,py=r->y+r->h;
 original(menu,x,y,push,data); /* owns/destroys record and clears global ONCE */
 *x=q(px,s.u);*y=q(py,s.u);
}
