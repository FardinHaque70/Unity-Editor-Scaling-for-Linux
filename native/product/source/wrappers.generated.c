#define _GNU_SOURCE
/* PRIVATE DIAGNOSTIC, NOT A RELEASE BACKEND.
 * Unity point P <-> GTK logical L: L=P*U, P=L/U at actual G=1.
 * Retains Unity's original GPU dimensions/PPP path; replaces Unity wrappers,
 * not global GTK functions. Full-function replacements avoid trampolines.
 */
#include <dlfcn.h>
#include <elf.h>
#include <fcntl.h>
#include <link.h>
#include <math.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "v6_epoch_bridge.h"
#include "geometry/extras.h"
typedef struct { int x,y,w,h; } IRect;
typedef struct { float x,y,w,h; } FRect;
typedef struct { float x,y; } FVec;
static double ep_factor(void) { ep_snapshot s; if(v6_conversion_snapshot_site(31,&s))abort(); if(s.mode!=EP_CUSTOM)abort(); return s.u; }
static uintptr_t image;
static int logfd = -1;
static atomic_uint lines;
/* Diagnostic sampling changes only: avoid filling the cap with idle repaint
 * repeats before the managed fixture has initialized. Not a latency measure. */
static int changed(uintptr_t key,int a,int b,int c,int d){
    typedef struct{uintptr_t key;int a,b,c,d;} Slot;static Slot slots[256];
    if(logfd<0)return 0;
    Slot*s=&slots[((key>>4)^(key*0x9e3779b1u))%256];
    if(s->key==key&&s->a==a&&s->b==b&&s->c==c&&s->d==d)return 0;
    *s=(Slot){key,a,b,c,d};return 1;
}
static void __attribute__((unused)) die(const char *why) { dprintf(2,"native scaling lab refused: %s\n",why); _exit(126); }
static void note(const char *fmt, ...) {
    if(logfd<0 || atomic_fetch_add(&lines,1)>=8000) return;
    char b[1024]; struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    int n=snprintf(b,sizeof(b),"%ld.%09ld ",(long)t.tv_sec,t.tv_nsec);
    va_list ap; va_start(ap,fmt); int m=vsnprintf(b+n,sizeof(b)-(size_t)n,fmt,ap); va_end(ap);
    size_t len=(m<0)?(size_t)n:(size_t)n+(size_t)m;
    if(len>=sizeof(b)-1)len=sizeof(b)-2;
    b[len++]='\n'; (void)write(logfd,b,len);
}
#define DECL(ret,name,...) static ret (*p_##name)(__VA_ARGS__)
DECL(void,gtk_widget_get_allocation,void*,IRect*);
DECL(int,gtk_widget_get_mapped,void*);
DECL(int,gtk_widget_get_scale_factor,void*);
DECL(void*,gtk_widget_get_window,void*);
DECL(unsigned long,gdk_x11_window_get_xid,void*);
DECL(void,gtk_widget_set_size_request,void*,int,int);
DECL(void,gtk_window_get_size,void*,int*,int*);
DECL(void,gtk_window_resize,void*,int,int);
DECL(void,gtk_window_set_default_size,void*,int,int);
DECL(void,gtk_window_set_geometry_hints,void*,void*,void*,int);
DECL(void,gtk_window_get_position,void*,int*,int*);
DECL(void,gtk_window_move,void*,int,int);
DECL(void,gtk_fixed_put,void*,void*,int,int);
DECL(void,gtk_fixed_move,void*,void*,int,int);
DECL(void*,gdk_display_get_default,void);
DECL(void*,gdk_display_get_monitor_at_point,void*,int,int);
DECL(void,gdk_monitor_get_geometry,void*,IRect*);
DECL(void,gdk_monitor_get_workarea,void*,IRect*);
DECL(void*,gdk_get_default_root_window,void);
DECL(int,gdk_window_get_width,void*);
DECL(int,gdk_window_get_height,void*);
DECL(void*,gdk_display_get_device_manager,void*);
DECL(void*,gdk_device_manager_get_client_pointer,void*);
DECL(void,gdk_device_get_position,void*,void**,int*,int*);
DECL(void*,gdk_window_get_device_position,void*,void*,int*,int*,unsigned*);
DECL(void*,gdk_window_get_display,void*);
DECL(void*,gdk_window_get_screen,void*);
DECL(void,gdk_display_warp_pointer,void*,void*,int,int);
DECL(void*,gdk_display_get_default_seat,void*);
DECL(void*,gdk_seat_get_pointer,void*);
DECL(void*,gdk_display_get_default_screen,void*);
DECL(void,gdk_device_warp,void*,void*,int,int);
DECL(int,gdk_event_get_scroll_deltas,void*,double*,double*);
DECL(void,gtk_widget_get_pointer,void*,int*,int*);
DECL(int,gdk_window_get_origin,void*,int*,int*);
DECL(void*,gdk_window_get_pointer,void*,int*,int*,unsigned*);
DECL(void,gdk_window_get_root_origin,void*,int*,int*);
DECL(int,gdk_screen_get_monitor_at_window,void*,void*);
DECL(void,gdk_screen_get_monitor_workarea,void*,int,IRect*);
DECL(unsigned,gtk_get_current_event_time,void);
typedef void(*PositionCallback)(void*,int*,int*,int*,void*);
DECL(void,gtk_menu_popup,void*,void*,void*,PositionCallback,void*,unsigned,unsigned);
static void (*original_widget_size)(void*w,int*a,int*b);
static void (*original_set_widget_size)(void*w,int a,int b);
static IRect (*original_allocation_rect)(IRect*r);
static void (*original_widget_rect)(void*w,int*x,int*y,int*a,int*b);
static void (*original_rectangle_values)(IRect*r,int*x,int*y,int*w,int*h);
static void (*original_monitor_position)(int x,int y,int*rx,int*ry,int*rw,int*rh);
static void (*original_monitor_rect)(const FRect*r,IRect*out);
static void (*original_pointer_screen)(int*x,int*y);
static void (*original_pointer_relative)(void*w,int*x,int*y);
static void (*original_warp_pointer)(void*w,int x,int y);
static void (*original_warp_device)(int x,int y);
static void (*original_widget_pointer)(void*w,int*x,int*y);
static void (*original_screen_center)(void*w,int*x,int*y);
static int (*original_window_origin)(void*g,int*x,int*y);
static void (*original_window_minmax)(void*w,const FVec*min,const FVec*max);
static void (*original_window_default)(void*w,int x,int y);
static float (*original_window_scale)(void*w);
static void (*original_window_size)(void*w,int*x,int*y);
static void (*original_set_window_size)(void*w,int x,int y);
static void (*original_window_position)(void*w,int*x,int*y);
static void (*original_set_window_position)(void*w,int x,int y);
static void (*original_fixed_put)(void*w,void*c,int x,int y);
static void (*original_fixed_move)(void*w,void*c,int x,int y);
static void (*original_motion)(void*e,double*x,double*y,double*rx,double*ry,unsigned*state,unsigned*time);
static void (*original_button)(void*e,int*x,int*y,int*rx,int*ry,unsigned*button,unsigned*state,unsigned*time);
static FRect (*original_configure)(void*e);
static void (*original_scroll)(void*e,double*x,double*y,double*dx,double*dy,int*dir,unsigned*state,unsigned*time);
static void (*original_crossing)(void*e,int*x,int*y,int*rx,int*ry,unsigned*state);
static void (*original_popup)(void*menu,PositionCallback callback);
static float (*original_player_scale)(void*w);
static void (*original_drag)(void*w,int*x,int*y,int*rx,int*ry,unsigned*state);
static int logical(int p) { return (int)lround((double)p*ep_factor()); }
static int points(int l) { return (int)lround((double)l/ep_factor()); }
static int request(int p) { return p<0?p:logical(p); }
static IRect point_rect(IRect r) { return (IRect){points(r.x),points(r.y),points(r.w),points(r.h)}; }
static void g1(void *w) { if(w && p_gtk_widget_get_scale_factor(w)!=1)die("actual GTK G != 1"); }
static unsigned long xid(void *w) { void *g=w?p_gtk_widget_get_window(w):NULL; return g?p_gdk_x11_window_get_xid(g):0; }
static double rd(void*e,int o){double d;memcpy(&d,(char*)e+o,8);return d;}
static unsigned ru(void*e,int o){unsigned u;memcpy(&u,(char*)e+o,4);return u;}
static void h_widget_size(void*w,int*a,int*b) { ep_snapshot operation; if(v6_conversion_snapshot_site(0,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_widget_size)abort(); return original_widget_size(w,a,b); }

    IRect r;g1(w);p_gtk_widget_get_allocation(w,&r); *a=points(r.w);*b=points(r.h);
    if(changed((uintptr_t)w,r.x,r.y,r.w,r.h))note("widget_size widget=%p xid=%lx actual=%d,%d,%d,%d point=%d,%d caller=%lx",w,xid(w),r.x,r.y,r.w,r.h,*a,*b,(unsigned long)((uintptr_t)__builtin_return_address(0)-image));
}
static void h_set_widget_size(void*w,int a,int b){ ep_snapshot operation; if(v6_conversion_snapshot_site(1,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_set_widget_size)abort(); return original_set_widget_size(w,a,b); }
g1(w);note("set_widget_size %p point=%d,%d gtk=%d,%d",w,a,b,request(a),request(b));p_gtk_widget_set_size_request(w,request(a),request(b));}
static IRect h_allocation_rect(IRect*r){ ep_snapshot operation; if(v6_conversion_snapshot_site(2,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_allocation_rect)abort(); return original_allocation_rect(r); }
IRect p=point_rect(*r);note("allocation point=%d,%d,%d,%d actual=%d,%d,%d,%d",p.x,p.y,p.w,p.h,r->x,r->y,r->w,r->h);return p;}
static void h_rectangle_values(IRect*r,int*x,int*y,int*w,int*h){ ep_snapshot operation; if(v6_conversion_snapshot_site(4,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_rectangle_values)abort(); return original_rectangle_values(r,x,y,w,h); }
IRect a=point_rect(*r);*x=a.x;*y=a.y;*w=a.w;*h=a.h;}
static void h_widget_rect(void*w,int*x,int*y,int*a,int*b){ ep_snapshot operation; if(v6_conversion_snapshot_site(3,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_widget_rect)abort(); return original_widget_rect(w,x,y,a,b); }
IRect r={0};g1(w);if(p_gtk_widget_get_mapped(w))p_gtk_widget_get_allocation(w,&r);r=point_rect(r);*x=r.x;*y=r.y;*a=r.w;*b=r.h;}
static void h_monitor_position(int x,int y,int*rx,int*ry,int*rw,int*rh){ ep_snapshot operation; if(v6_conversion_snapshot_site(5,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_monitor_position)abort(); return original_monitor_position(x,y,rx,ry,rw,rh); }
IRect r={0};void*m=p_gdk_display_get_monitor_at_point(p_gdk_display_get_default(),logical(x),logical(y));if(m)p_gdk_monitor_get_geometry(m,&r);r=point_rect(r);*rx=r.x;*ry=r.y;*rw=r.w;*rh=r.h;}
static void h_monitor_rect(const FRect*r,IRect*out){ ep_snapshot operation; if(v6_conversion_snapshot_site(6,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_monitor_rect)abort(); return original_monitor_rect(r,out); }

    IRect a={0};void*m=p_gdk_display_get_monitor_at_point(p_gdk_display_get_default(),(int)lround(((double)r->x+r->w*.5)*operation_u),(int)lround(((double)r->y+r->h*.5)*operation_u));
    if(m)p_gdk_monitor_get_workarea(m,&a);else{void*g=p_gdk_get_default_root_window();a.w=p_gdk_window_get_width(g);a.h=p_gdk_window_get_height(g);}*out=point_rect(a);
}
static void* pointer(void){return p_gdk_device_manager_get_client_pointer(p_gdk_display_get_device_manager(p_gdk_display_get_default()));}
static void h_pointer_screen(int*x,int*y){ ep_snapshot operation; if(v6_conversion_snapshot_site(7,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_pointer_screen)abort(); return original_pointer_screen(x,y); }
int a=0,b=0;p_gdk_device_get_position(pointer(),NULL,&a,&b);*x=points(a);*y=points(b);}
static void h_pointer_relative(void*w,int*x,int*y){ ep_snapshot operation; if(v6_conversion_snapshot_site(8,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_pointer_relative)abort(); return original_pointer_relative(w,x,y); }
int a=0,b=0;g1(w);p_gdk_window_get_device_position(p_gtk_widget_get_window(w),pointer(),&a,&b,NULL);*x=points(a);*y=points(b);}
static void h_warp_pointer(void*w,int x,int y){ ep_snapshot operation; if(v6_conversion_snapshot_site(9,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_warp_pointer)abort(); return original_warp_pointer(w,x,y); }
void*g=p_gtk_widget_get_window(w);p_gdk_display_warp_pointer(p_gdk_window_get_display(g),p_gdk_window_get_screen(g),logical(x),logical(y));}
static void h_warp_device(int x,int y){ ep_snapshot operation; if(v6_conversion_snapshot_site(10,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_warp_device)abort(); return original_warp_device(x,y); }
void*d=p_gdk_display_get_default();p_gdk_device_warp(p_gdk_seat_get_pointer(p_gdk_display_get_default_seat(d)),p_gdk_display_get_default_screen(d),logical(x),logical(y));}
static void h_widget_pointer(void*w,int*x,int*y){ ep_snapshot operation; if(v6_conversion_snapshot_site(11,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_widget_pointer)abort(); return original_widget_pointer(w,x,y); }
int a=0,b=0;g1(w);p_gtk_widget_get_pointer(w,&a,&b);*x=points(a);*y=points(b);}
static int h_window_origin(void*g,int*x,int*y){ ep_snapshot operation; if(v6_conversion_snapshot_site(13,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_window_origin)abort(); return original_window_origin(g,x,y); }
int a=0,b=0;int result=p_gdk_window_get_origin(g,&a,&b);*x=points(a);*y=points(b);return result;}
static void h_screen_center(void*w,int*x,int*y){ ep_snapshot operation; if(v6_conversion_snapshot_site(12,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_screen_center)abort(); return original_screen_center(w,x,y); }
void*g=w?p_gtk_widget_get_window(w):NULL;void*s=g?p_gdk_window_get_screen(g):p_gdk_display_get_default_screen(p_gdk_display_get_default());IRect r={0};int m=p_gdk_screen_get_monitor_at_window(s,g);p_gdk_screen_get_monitor_workarea(s,m,&r);*x=points(r.x+r.w/2);*y=points(r.y+r.h/2);}
static void h_window_minmax(void*w,const FVec*min,const FVec*max){ ep_snapshot operation; if(v6_conversion_snapshot_site(14,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_window_minmax)abort(); return original_window_minmax(w,min,max); }
int geometry[16]={0};g1(w);geometry[0]=(int)((double)min->x*operation_u);geometry[1]=(int)((double)min->y*operation_u);geometry[2]=(int)((double)max->x*operation_u);geometry[3]=(int)((double)max->y*operation_u);p_gtk_window_set_geometry_hints(w,NULL,geometry,6);}
static void h_window_default(void*w,int x,int y){ ep_snapshot operation; if(v6_conversion_snapshot_site(15,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_window_default)abort(); return original_window_default(w,x,y); }
g1(w);p_gtk_window_set_default_size(w,request(x),request(y));}
static float h_window_scale(void*w){ ep_snapshot operation; if(v6_conversion_snapshot_site(16,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_window_scale)abort(); return original_window_scale(w); }
g1(w);return (float)operation_u;}
/* These player helpers now consume/produce virtual native points. Their
 * previous DPI multiplier would apply U twice after wrapper conversion. */
static float h_player_scale(void*w){ ep_snapshot operation; if(v6_conversion_snapshot_site(29,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_player_scale)abort(); return original_player_scale(w); }
g1(w);return 1.0f;}
static void h_window_size(void*w,int*x,int*y){ ep_snapshot operation; if(v6_conversion_snapshot_site(17,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_window_size)abort(); return original_window_size(w,x,y); }
int a=0,b=0;g1(w);p_gtk_window_get_size(w,&a,&b);*x=points(a);*y=points(b);note("window_size widget=%p xid=%lx actual=%d,%d point=%d,%d",w,xid(w),a,b,*x,*y);}
static void h_set_window_size(void*w,int x,int y){ ep_snapshot operation; if(v6_conversion_snapshot_site(18,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_set_window_size)abort(); return original_set_window_size(w,x,y); }
g1(w);note("set_window_size %p point=%d,%d gtk=%d,%d",w,x,y,logical(x),logical(y));p_gtk_window_resize(w,logical(x),logical(y));}
static void h_window_position(void*w,int*x,int*y){ ep_snapshot operation; if(v6_conversion_snapshot_site(19,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_window_position)abort(); return original_window_position(w,x,y); }
int a=0,b=0;g1(w);p_gtk_window_get_position(w,&a,&b);*x=points(a);*y=points(b);}
static void h_set_window_position(void*w,int x,int y){ ep_snapshot operation; if(v6_conversion_snapshot_site(20,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_set_window_position)abort(); return original_set_window_position(w,x,y); }
g1(w);p_gtk_window_move(w,logical(x),logical(y));}
static void h_fixed_put(void*w,void*c,int x,int y){ ep_snapshot operation; if(v6_conversion_snapshot_site(21,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_fixed_put)abort(); return original_fixed_put(w,c,x,y); }
g1(w);p_gtk_fixed_put(w,c,logical(x),logical(y));}
static void h_fixed_move(void*w,void*c,int x,int y){ ep_snapshot operation; if(v6_conversion_snapshot_site(22,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_fixed_move)abort(); return original_fixed_move(w,c,x,y); }
g1(w);note("fixed_move child=%p point=%d,%d gtk=%d,%d",c,x,y,logical(x),logical(y));p_gtk_fixed_move(w,c,logical(x),logical(y));}
static void h_motion(void*e,double*x,double*y,double*rx,double*ry,unsigned*state,unsigned*time){ ep_snapshot operation; if(v6_conversion_snapshot_site(23,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_motion)abort(); return original_motion(e,x,y,rx,ry,state,time); }

    *x=rd(e,24)/operation_u;*y=rd(e,32)/operation_u;*rx=rd(e,64)/operation_u;*ry=rd(e,72)/operation_u;*state=ru(e,48);*time=ru(e,20);
    note("motion local_gtk=%.3f,%.3f point=%.3f,%.3f root_point=%.3f,%.3f gdk_time=%u",rd(e,24),rd(e,32),*x,*y,*rx,*ry,*time);
}
static void h_button(void*e,int*x,int*y,int*rx,int*ry,unsigned*button,unsigned*state,unsigned*time){ ep_snapshot operation; if(v6_conversion_snapshot_site(24,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_button)abort(); return original_button(e,x,y,rx,ry,button,state,time); }

    *x=(int)(rd(e,24)/operation_u);*y=(int)(rd(e,32)/operation_u);*rx=(int)(rd(e,64)/operation_u);*ry=(int)(rd(e,72)/operation_u);*state=ru(e,48);*time=ru(e,20);
    unsigned b=ru(e,52);if(b==2)*button=2;else if(b==3)*button=1;else if(b==8)*button=11;else if(b==9)*button=10;else *button=b-1;
    note("button type=%u local_gtk=%.3f,%.3f point=%d,%d button=%u gdk_time=%u",ru(e,0),rd(e,24),rd(e,32),*x,*y,*button,*time);
}
static FRect h_configure(void*e){ ep_snapshot operation; if(v6_conversion_snapshot_site(25,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_configure)abort(); return original_configure(e); }
FRect r={(float)(int)ru(e,20)/(float)operation_u,(float)(int)ru(e,24)/(float)operation_u,(float)(int)ru(e,28)/(float)operation_u,(float)(int)ru(e,32)/(float)operation_u};note("configure point=%f,%f,%f,%f",r.x,r.y,r.w,r.h);return r;}
static void h_scroll(void*e,double*x,double*y,double*dx,double*dy,int*dir,unsigned*state,unsigned*time){ ep_snapshot operation; if(v6_conversion_snapshot_site(26,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_scroll)abort(); return original_scroll(e,x,y,dx,dy,dir,state,time); }
*x=rd(e,24)/operation_u;*y=rd(e,32)/operation_u;*state=ru(e,40);*time=ru(e,20);*dir=(int)ru(e,44);if(*dir==4)p_gdk_event_get_scroll_deltas(e,dx,dy);}
static void h_crossing(void*e,int*x,int*y,int*rx,int*ry,unsigned*state){ ep_snapshot operation; if(v6_conversion_snapshot_site(27,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_crossing)abort(); return original_crossing(e,x,y,rx,ry,state); }
*x=(int)(rd(e,40)/operation_u);*y=(int)(rd(e,48)/operation_u);*rx=(int)(rd(e,56)/operation_u);*ry=(int)(rd(e,64)/operation_u);*state=ru(e,32);}
static void h_drag(void*w,int*x,int*y,int*rx,int*ry,unsigned*state){ ep_snapshot operation; if(v6_conversion_snapshot_site(30,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_drag)abort(); return original_drag(w,x,y,rx,ry,state); }
int a=0,b=0,c=0,d=0;void*g=p_gtk_widget_get_window(w);g1(w);p_gdk_window_get_pointer(g,&a,&b,state);p_gdk_window_get_root_origin(g,&c,&d);*x=points(a);*y=points(b);*rx=points(c+a);*ry=points(d+b);}
static void __attribute__((unused)) popup_position(void*menu,int*x,int*y,int*push,void*data){
    (void)data;PositionCallback original=(PositionCallback)(image+0x3bc3770);
    original(menu,x,y,push,NULL);int px=*x,py=*y;*x=logical(px);*y=logical(py);
    note("popup_position point=%d,%d gtk=%d,%d",px,py,*x,*y);
}
static void h_popup(void*menu,PositionCallback callback){ ep_snapshot operation; if(v6_conversion_snapshot_site(28,&operation))abort(); const double operation_u __attribute__((unused))=operation.u; if(operation.mode==EP_DEFAULT) { if(!original_popup)abort(); return original_popup(menu,callback); }

    if(callback && (uintptr_t)callback!=image+0x3bc3770)die("unreviewed popup callback");
    p_gtk_menu_popup(menu,NULL,NULL,callback?v6_precise_popup:NULL,NULL,0,p_gtk_get_current_event_time());
}


struct ep_candidate { const char *name; uintptr_t va; void *replacement; void **original; };
static struct ep_candidate candidates[]={
{"widget_size",0x3c03010,(void*)h_widget_size,(void**)&original_widget_size},
{"set_widget_size",0x3c03040,(void*)h_set_widget_size,(void**)&original_set_widget_size},
{"allocation_rect",0x3c03050,(void*)h_allocation_rect,(void**)&original_allocation_rect},
{"widget_rect",0x3c03060,(void*)h_widget_rect,(void**)&original_widget_rect},
{"rectangle_values",0x3c03110,(void*)h_rectangle_values,(void**)&original_rectangle_values},
{"monitor_position",0x3c03170,(void*)h_monitor_position,(void**)&original_monitor_position},
{"monitor_rect",0x3c031e0,(void*)h_monitor_rect,(void**)&original_monitor_rect},
{"pointer_screen",0x3c032a0,(void*)h_pointer_screen,(void**)&original_pointer_screen},
{"pointer_relative",0x3c032e0,(void*)h_pointer_relative,(void**)&original_pointer_relative},
{"warp_pointer",0x3c03390,(void*)h_warp_pointer,(void**)&original_warp_pointer},
{"warp_device",0x3c033e0,(void*)h_warp_device,(void**)&original_warp_device},
{"widget_pointer",0x3c03570,(void*)h_widget_pointer,(void**)&original_widget_pointer},
{"screen_center",0x3c03580,(void*)h_screen_center,(void**)&original_screen_center},
{"window_origin",0x3c03750,(void*)h_window_origin,(void**)&original_window_origin},
{"window_minmax",0x3c03c00,(void*)h_window_minmax,(void**)&original_window_minmax},
{"window_default",0x3c04940,(void*)h_window_default,(void**)&original_window_default},
{"window_scale",0x3c04a50,(void*)h_window_scale,(void**)&original_window_scale},
{"window_size",0x3c060d0,(void*)h_window_size,(void**)&original_window_size},
{"set_window_size",0x3c06110,(void*)h_set_window_size,(void**)&original_set_window_size},
{"window_position",0x3c06170,(void*)h_window_position,(void**)&original_window_position},
{"set_window_position",0x3c061b0,(void*)h_set_window_position,(void**)&original_set_window_position},
{"fixed_put",0x3c063c0,(void*)h_fixed_put,(void**)&original_fixed_put},
{"fixed_move",0x3c06400,(void*)h_fixed_move,(void**)&original_fixed_move},
{"motion",0x3c07b40,(void*)h_motion,(void**)&original_motion},
{"button",0x3c07b80,(void*)h_button,(void**)&original_button},
{"configure",0x3c07be0,(void*)h_configure,(void**)&original_configure},
{"scroll",0x3c07bf0,(void*)h_scroll,(void**)&original_scroll},
{"crossing",0x3c07c30,(void*)h_crossing,(void**)&original_crossing},
{"popup",0x3c07a40,(void*)h_popup,(void**)&original_popup},
{"player_scale",0x3bf8340,(void*)h_player_scale,(void**)&original_player_scale},
{"drag",0x3c07d70,(void*)h_drag,(void**)&original_drag}
};
size_t ep_wrapper_count(void){return sizeof(candidates)/sizeof(candidates[0]);}
const struct ep_candidate *ep_wrapper_candidates(void){return candidates;}
int ep_wrapper_bind_gtk(uintptr_t base){ image=base;
 *(void**)(&p_gtk_widget_get_allocation)=dlsym(RTLD_DEFAULT,"gtk_widget_get_allocation"); if(!p_gtk_widget_get_allocation)return -1;
 *(void**)(&p_gtk_widget_get_mapped)=dlsym(RTLD_DEFAULT,"gtk_widget_get_mapped"); if(!p_gtk_widget_get_mapped)return -1;
 *(void**)(&p_gtk_widget_get_scale_factor)=dlsym(RTLD_DEFAULT,"gtk_widget_get_scale_factor"); if(!p_gtk_widget_get_scale_factor)return -1;
 *(void**)(&p_gtk_widget_get_window)=dlsym(RTLD_DEFAULT,"gtk_widget_get_window"); if(!p_gtk_widget_get_window)return -1;
 *(void**)(&p_gdk_x11_window_get_xid)=dlsym(RTLD_DEFAULT,"gdk_x11_window_get_xid"); if(!p_gdk_x11_window_get_xid)return -1;
 *(void**)(&p_gtk_widget_set_size_request)=dlsym(RTLD_DEFAULT,"gtk_widget_set_size_request"); if(!p_gtk_widget_set_size_request)return -1;
 *(void**)(&p_gtk_window_get_size)=dlsym(RTLD_DEFAULT,"gtk_window_get_size"); if(!p_gtk_window_get_size)return -1;
 *(void**)(&p_gtk_window_resize)=dlsym(RTLD_DEFAULT,"gtk_window_resize"); if(!p_gtk_window_resize)return -1;
 *(void**)(&p_gtk_window_set_default_size)=dlsym(RTLD_DEFAULT,"gtk_window_set_default_size"); if(!p_gtk_window_set_default_size)return -1;
 *(void**)(&p_gtk_window_set_geometry_hints)=dlsym(RTLD_DEFAULT,"gtk_window_set_geometry_hints"); if(!p_gtk_window_set_geometry_hints)return -1;
 *(void**)(&p_gtk_window_get_position)=dlsym(RTLD_DEFAULT,"gtk_window_get_position"); if(!p_gtk_window_get_position)return -1;
 *(void**)(&p_gtk_window_move)=dlsym(RTLD_DEFAULT,"gtk_window_move"); if(!p_gtk_window_move)return -1;
 *(void**)(&p_gtk_fixed_put)=dlsym(RTLD_DEFAULT,"gtk_fixed_put"); if(!p_gtk_fixed_put)return -1;
 *(void**)(&p_gtk_fixed_move)=dlsym(RTLD_DEFAULT,"gtk_fixed_move"); if(!p_gtk_fixed_move)return -1;
 *(void**)(&p_gdk_display_get_default)=dlsym(RTLD_DEFAULT,"gdk_display_get_default"); if(!p_gdk_display_get_default)return -1;
 *(void**)(&p_gdk_display_get_monitor_at_point)=dlsym(RTLD_DEFAULT,"gdk_display_get_monitor_at_point"); if(!p_gdk_display_get_monitor_at_point)return -1;
 *(void**)(&p_gdk_monitor_get_geometry)=dlsym(RTLD_DEFAULT,"gdk_monitor_get_geometry"); if(!p_gdk_monitor_get_geometry)return -1;
 *(void**)(&p_gdk_monitor_get_workarea)=dlsym(RTLD_DEFAULT,"gdk_monitor_get_workarea"); if(!p_gdk_monitor_get_workarea)return -1;
 *(void**)(&p_gdk_get_default_root_window)=dlsym(RTLD_DEFAULT,"gdk_get_default_root_window"); if(!p_gdk_get_default_root_window)return -1;
 *(void**)(&p_gdk_window_get_width)=dlsym(RTLD_DEFAULT,"gdk_window_get_width"); if(!p_gdk_window_get_width)return -1;
 *(void**)(&p_gdk_window_get_height)=dlsym(RTLD_DEFAULT,"gdk_window_get_height"); if(!p_gdk_window_get_height)return -1;
 *(void**)(&p_gdk_display_get_device_manager)=dlsym(RTLD_DEFAULT,"gdk_display_get_device_manager"); if(!p_gdk_display_get_device_manager)return -1;
 *(void**)(&p_gdk_device_manager_get_client_pointer)=dlsym(RTLD_DEFAULT,"gdk_device_manager_get_client_pointer"); if(!p_gdk_device_manager_get_client_pointer)return -1;
 *(void**)(&p_gdk_device_get_position)=dlsym(RTLD_DEFAULT,"gdk_device_get_position"); if(!p_gdk_device_get_position)return -1;
 *(void**)(&p_gdk_window_get_device_position)=dlsym(RTLD_DEFAULT,"gdk_window_get_device_position"); if(!p_gdk_window_get_device_position)return -1;
 *(void**)(&p_gdk_window_get_display)=dlsym(RTLD_DEFAULT,"gdk_window_get_display"); if(!p_gdk_window_get_display)return -1;
 *(void**)(&p_gdk_window_get_screen)=dlsym(RTLD_DEFAULT,"gdk_window_get_screen"); if(!p_gdk_window_get_screen)return -1;
 *(void**)(&p_gdk_display_warp_pointer)=dlsym(RTLD_DEFAULT,"gdk_display_warp_pointer"); if(!p_gdk_display_warp_pointer)return -1;
 *(void**)(&p_gdk_display_get_default_seat)=dlsym(RTLD_DEFAULT,"gdk_display_get_default_seat"); if(!p_gdk_display_get_default_seat)return -1;
 *(void**)(&p_gdk_seat_get_pointer)=dlsym(RTLD_DEFAULT,"gdk_seat_get_pointer"); if(!p_gdk_seat_get_pointer)return -1;
 *(void**)(&p_gdk_display_get_default_screen)=dlsym(RTLD_DEFAULT,"gdk_display_get_default_screen"); if(!p_gdk_display_get_default_screen)return -1;
 *(void**)(&p_gdk_device_warp)=dlsym(RTLD_DEFAULT,"gdk_device_warp"); if(!p_gdk_device_warp)return -1;
 *(void**)(&p_gdk_event_get_scroll_deltas)=dlsym(RTLD_DEFAULT,"gdk_event_get_scroll_deltas"); if(!p_gdk_event_get_scroll_deltas)return -1;
 *(void**)(&p_gtk_widget_get_pointer)=dlsym(RTLD_DEFAULT,"gtk_widget_get_pointer"); if(!p_gtk_widget_get_pointer)return -1;
 *(void**)(&p_gdk_window_get_origin)=dlsym(RTLD_DEFAULT,"gdk_window_get_origin"); if(!p_gdk_window_get_origin)return -1;
 *(void**)(&p_gdk_window_get_pointer)=dlsym(RTLD_DEFAULT,"gdk_window_get_pointer"); if(!p_gdk_window_get_pointer)return -1;
 *(void**)(&p_gdk_window_get_root_origin)=dlsym(RTLD_DEFAULT,"gdk_window_get_root_origin"); if(!p_gdk_window_get_root_origin)return -1;
 *(void**)(&p_gdk_screen_get_monitor_at_window)=dlsym(RTLD_DEFAULT,"gdk_screen_get_monitor_at_window"); if(!p_gdk_screen_get_monitor_at_window)return -1;
 *(void**)(&p_gdk_screen_get_monitor_workarea)=dlsym(RTLD_DEFAULT,"gdk_screen_get_monitor_workarea"); if(!p_gdk_screen_get_monitor_workarea)return -1;
 *(void**)(&p_gtk_get_current_event_time)=dlsym(RTLD_DEFAULT,"gtk_get_current_event_time"); if(!p_gtk_get_current_event_time)return -1;
 *(void**)(&p_gtk_menu_popup)=dlsym(RTLD_DEFAULT,"gtk_menu_popup"); if(!p_gtk_menu_popup)return -1;
return 0; }
/* Own the P -> backing boundary once. Called on Unity's original GTK thread.
 * Never reconstruct actual pixel dimensions from int(point)*U. */
uint64_t ep_actual_pixels(void*view){
    void*w=*(void**)((char*)view+0x10);IRect a={0};g1(w);
    p_gtk_widget_get_allocation(w,&a);
    if(a.w<1||a.h<1)die("invalid actual GTK allocation");
    void*g=*(void**)((char*)view+0xf8);int oldw=0,oldh=0;
    if(g){memcpy(&oldw,(char*)g+0x68,4);memcpy(&oldh,(char*)g+0x6c,4);}
    int pw=0,ph=0;float u=0;memcpy(&pw,(char*)view+0x20,4);memcpy(&ph,(char*)view+0x24,4);memcpy(&u,(char*)view+0x2c,4);
    if(changed((uintptr_t)view+1,a.w,a.h,oldw,oldh))note("backing view=%p widget=%p xid=%lx P=%d,%d U=%f actual=%d,%d previous_gfx=%d,%d",view,w,xid(w),pw,ph,u,a.w,a.h,oldw,oldh);
    return (uint64_t)(uint32_t)a.w|((uint64_t)(uint32_t)a.h<<32);
}
static uint64_t current_backing(void*view){
    void*g=*(void**)((char*)view+0xf8);
    if(!g)return ep_actual_pixels(view);
    int w,h;memcpy(&w,(char*)g+0x68,4);memcpy(&h,(char*)g+0x6c,4);
    if(w<1||h<1)die("invalid GfxWindow backing dimensions");
    return (uint64_t)(uint32_t)w|((uint64_t)(uint32_t)h<<32);
}
void* ep_backing_viewport(void*view){
    uint64_t size=current_backing(view);IRect r={0,0,(int)(uint32_t)size,(int)(uint32_t)(size>>32)};
    void*(*get_gfx)(void)=(void*(*)(void))(image+0x249efc0);
    void*gfx=get_gfx();void**vt=*(void***)gfx;
    void(*set_viewport)(void*,const IRect*)=(void(*)(void*,const IRect*))vt[0x1c8/8];
    set_viewport(gfx,&r);
    if(changed((uintptr_t)view+2,r.w,r.h,0,0))note("viewport view=%p actual_backing=%d,%d",view,r.w,r.h);
    return gfx; /* original DoPaint continuation needs this in RBP */
}
void ep_backing_screen(void*manager,void*view){
    uint64_t size=current_backing(view);int w=(int)(uint32_t)size,h=(int)(uint32_t)(size>>32);
    void(*setup)(void*,float,float)=(void(*)(void*,float,float))(image+0x4496ab0);
    setup(manager,(float)w,(float)h);
    if(changed((uintptr_t)view+3,w,h,0,0))note("screen_manager view=%p actual_backing=%d,%d",view,w,h);
}
