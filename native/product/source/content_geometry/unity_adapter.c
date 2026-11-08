#include "unity_adapter.h"
#include <gtk/gtk.h>
#include <string.h>
static int resolve(void*context,uint64_t native,uint64_t generation,cg_identity*out){
 cg_unity_context*c=context;
 if(!c||!c->admit)return CG_OWNER;
 int rc=c->admit(c->owner_context,native,generation);if(rc)return rc;
 /* Only after mandatory native owner/registry admission may fields be read. */
 const unsigned char*p=(const unsigned char*)(uintptr_t)native;
 memset(out,0,sizeof(*out));out->native=native;out->generation=generation;
 memcpy(&out->mode,p+0x40,4);memcpy(&out->top,p+0xa8,sizeof(void*));memcpy(&out->fixed,p+0xb0,sizeof(void*));memcpy(out->cached_points,p+0x30,16);
 if(out->mode==4&&c->main_menubar)out->menubar=c->main_menubar(c->owner_context,native);
 return CG_OK;
}
static void* parent(void*c,void*w){(void)c;return gtk_widget_get_parent(GTK_WIDGET(w));}
static int widget(void*c,void*w,cg_widget*out){
 (void)c;if(!GTK_IS_WIDGET(w))return CG_NOT_READY;
 GtkAllocation a;gtk_widget_get_allocation(w,&a);
 *out=(cg_widget){.allocation={a.x,a.y,a.width,a.height},.mapped=gtk_widget_get_mapped(w),.g=gtk_widget_get_scale_factor(w)};
 out->kind=GTK_IS_FIXED(w)?CG_FIXED:GTK_IS_VIEWPORT(w)?CG_VIEWPORT:GTK_IS_SCROLLED_WINDOW(w)?CG_SCROLLED:GTK_IS_MENU_BAR(w)?CG_MENUBAR:0;
 return CG_OK;
}
static int window(void*c,void*w,cg_rect*out){
 (void)c;if(!GTK_IS_WINDOW(w))return CG_NOT_READY;
 gtk_window_get_position(w,&out->x,&out->y);gtk_window_get_size(w,&out->w,&out->h);return CG_OK;
}
static int origin(void*c,void*w,int32_t xy[2]){
 (void)c;GdkWindow*g=gtk_widget_get_window(w);
 if(!g||!gdk_window_get_origin(g,&xy[0],&xy[1]))return CG_NOT_READY;
 return CG_OK;
}
cg_host cg_unity_host(cg_unity_context*c){return(cg_host){c,resolve,parent,widget,window,origin};}
