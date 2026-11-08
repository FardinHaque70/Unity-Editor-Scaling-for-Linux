#include "startup.h"
#include "config.generated.h"
#include "main_geometry/main.h"
#include "content_geometry/unity_adapter.h"
#include "geometry/birth.h"
#include "rendering/render_boundary.h"
#include "rendering/accepted_repaint.h"
#include "product/product_policy.h"
#include "product/host_environment.h"
#include <gtk/gtk.h>
#include <gdk/gdkx.h>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <sys/syscall.h>
#include <unistd.h>
extern "C" int ns_log_open(const char*,char*,size_t);

namespace {
ep_snapshot policy{};bool initialized,receipt_attempted;uintptr_t image;long owner;
ups_policy decision{UPS_POLICY_ABI,sizeof(ups_policy),UPS_UNKNOWN,0,0,0,0};int decision_rc=UPS_ARGUMENT;
std::atomic<unsigned> installed{0};GtkWidget*bar;int fd=-1,menu_dpi;unsigned trace_rows;
guint diagnostic_source;unsigned diagnostic_snapshots,diagnostic_limit=16;bool diagnostic_configured;
long tid(){return syscall(SYS_gettid);}
template<class T>T load(const void*p,size_t o){T r;memcpy(&r,(const char*)p+o,sizeof r);return r;}
bool main_thread(){return image&&owner==(long)getpid()&&tid()==owner;}
bool geometry_ready(){
 // Read-only native setters/allocations are legitimate on the saved Unity
 // thread even outside GLib dispatch or while Unity is executing managed code.
 // Do not initialize GtkEventManager merely to query an idle predicate.
 return main_thread()&&installed.load()&&*(unsigned char*)(image+0x60353b4)&&
        reinterpret_cast<unsigned char(*)()>(image+0x34bc540)();
}
bool valid(void*p){return reinterpret_cast<void*(*)(void*,void*)>(image+0x3b37cd0)((void*)(image+0x67ce468),p)!=nullptr;}
struct Read {uint64_t native,birth,generation;};
int admit(void*opaque,uint64_t native,uint64_t generation){
 auto*c=(Read*)opaque;
 if(!geometry_ready()||native!=c->native||generation!=c->generation||v6_birth_generation()!=generation||
    !valid((void*)native)||v6_birth_lookup(native,V6_BIRTH_WINDOW)!=c->birth)return CG_STALE;
 if(load<unsigned>((void*)native,0x40)!=4||load<unsigned char>((void*)native,0xc0)||load<unsigned char>((void*)native,0xc3))return CG_NOT_READY;
 return CG_OK;
}
void*menu(void*,uint64_t){return bar;}
gboolean diagnostics(gpointer){
 if(!main_thread())return G_SOURCE_REMOVE;
 if(diagnostic_snapshots>=diagnostic_limit){diagnostic_source=0;return G_SOURCE_REMOVE;}
 if(!geometry_ready()||!g_main_context_is_owner(g_main_context_default())||
    !*(unsigned char*)(image+0x6810588)||reinterpret_cast<unsigned char(*)()>(image+0x3c08fc0)())return G_SOURCE_CONTINUE;
 rb_snapshot boundary{};boundary.size=sizeof boundary;boundary.version=RB_ABI_VERSION;
 if(rb_query(&boundary)||boundary.active_total)return G_SOURCE_CONTINUE;
 unsigned windows=0,views=0;const unsigned sample=++diagnostic_snapshots;
 try{
 using Each=void(*)(void*,const std::function<void(void*)>&);
 std::function<void(void*)> window=[&](void*p){
  if(++windows>32||!valid(p)||!v6_birth_lookup((uint64_t)p,V6_BIRTH_WINDOW))return;
  GtkWidget*w=load<GtkWidget*>(p,0xa8);if(!w||!GTK_IS_WINDOW(w)||!gtk_widget_get_mapped(w))return;
  int x,y,width,height;gtk_window_get_position(GTK_WINDOW(w),&x,&y);gtk_window_get_size(GTK_WINDOW(w),&width,&height);
  float r[4];memcpy(r,(char*)p+0x30,sizeof r);
  dprintf(fd,"{\"event\":\"startup_window\",\"sample\":%u,\"native\":\"0x%llx\",\"mode\":%u,\"raw_client_L\":[%d,%d,%d,%d],\"cached_P\":[%.9g,%.9g,%.9g,%.9g]}\n",sample,(unsigned long long)p,load<unsigned>(p,0x40),x,y,width,height,r[0],r[1],r[2],r[3]);
 };
 std::function<void(void*)> view=[&](void*p){
  if(++views>128||!v6_birth_lookup((uint64_t)p,V6_BIRTH_VIEW))return;
  GtkWidget*w=load<GtkWidget*>(p,0x10);if(!w||!GTK_IS_WIDGET(w)||!gtk_widget_get_mapped(w))return;
  GtkAllocation a{};gtk_widget_get_allocation(w,&a);int backing[2]={0,0};void*gfx=load<void*>(p,0xf8);if(gfx)memcpy(backing,(char*)gfx+0x68,sizeof backing);
  const float u=load<float>(p,0x2c);
  dprintf(fd,"{\"event\":\"startup_view\",\"sample\":%u,\"native\":\"0x%llx\",\"allocation_L\":[%d,%d,%d,%d],\"backing\":[%d,%d],\"cached_U\":%.9g,\"G\":%d}\n",sample,(unsigned long long)p,a.x,a.y,a.width,a.height,backing[0],backing[1],u,gtk_widget_get_scale_factor(w));
 };
  reinterpret_cast<Each>(image+0x3b364e0)((void*)(image+0x67ce468),window);
  reinterpret_cast<Each>(image+0x3b367f0)((void*)(image+0x67ce468),view);
 }catch(...){ns_log("{\"event\":\"startup_diagnostic_refused\",\"reason\":\"native_exception\"}");diagnostic_source=0;return G_SOURCE_REMOVE;}
 dprintf(fd,"{\"event\":\"startup_snapshot\",\"sample\":%u,\"windows\":%u,\"views\":%u,\"production_applied\":false,\"presented\":false}\n",sample,windows,views);
 return G_SOURCE_CONTINUE;
}
}
extern "C" int ns_initialize(){
 if(initialized)return -1;
 const char*settings=getenv("UNITY_EDITOR_SCALING_SETTINGS"),*editor=getenv("UNITY_EDITOR_SCALING_PUBLIC_EDITOR");
 if((settings&&strcmp(settings,NS_SETTINGS_FILE))||(editor&&strcmp(editor,NS_PUBLIC_EDITOR)))return -1;
 decision_rc=ups_read_settings(NS_SETTINGS_FILE,NS_PUBLIC_EDITOR,getuid(),&decision);
 if(decision_rc!=UPS_OK)return -1;
 if(decision.mode==UPS_DEFAULT){policy={1,1,1,EP_DEFAULT,0,0};initialized=true;return 0;}
 if(decision.mode!=UPS_CUSTOM||decision.percent<100||decision.percent>200||
    decision.u!=(float)(decision.percent/100.0))return -1;
 policy={1,1,1,EP_CUSTOM,decision.percent,(double)decision.u};initialized=true;return 1;
}
extern "C" int v6_conversion_snapshot(ep_snapshot*out){if(!out||!initialized)return EP_GATE;*out=policy;return 0;}
extern "C" int v6_conversion_snapshot_site(unsigned,ep_snapshot*out){return v6_conversion_snapshot(out);}
extern "C" unsigned ns_percent(){return policy.percent;}
extern "C" void ns_log(const char*line){if(fd>=0&&tid()==(long)getpid()&&line)dprintf(fd,"%s\n",line);}
extern "C" void ns_bootstrap(uintptr_t base){
 if(base){image=base;nsp_repaint_bind(base);}if(receipt_attempted)return;receipt_attempted=true;
 const char*path=getenv("UNITY_EDITOR_SCALING_RECEIPT");
 if(path&&path[0]=='/'){
  char owned[4096];fd=ns_log_open(path,owned,sizeof owned);
  if(fd<0)dprintf(2,"Unity scaling: owner receipt unavailable; continuing without receipt.\n");
 }
 char line[512];snprintf(line,sizeof line,"{\"event\":\"product_policy\",\"contract\":\"product-profile-v1\",\"pid\":%ld,\"policy_rc\":%d,\"mode\":%u,\"percent\":%u,\"policy_factor\":%.9g,\"revision\":%llu,\"profile_present\":%u,\"native_installed\":false,\"actual_u_measured\":false,\"production_applied\":false,\"presented\":false}",(long)getpid(),decision_rc,decision.mode,decision.percent,(double)decision.u,(unsigned long long)decision.revision,decision.profile_present);ns_log(line);
}
extern "C" void ns_refused(const char*reason){
 char line[384];snprintf(line,sizeof line,"{\"event\":\"product_refusal\",\"reason\":\"%s\",\"native_installed\":false,\"production_applied\":false,\"presented\":false}",reason);ns_log(line);
}
extern "C" void ns_installed(){
 // All native guards and instruction installation have completed. GTK has not
 // initialized yet; these are this process's overrides only. Children restore
 // the captured host envelope before choosing their own fresh profile.
 if(setenv("GDK_SCALE","1",1)||setenv("GDK_DPI_SCALE","1",1)||setenv("GDK_BACKEND","x11",1)){
  (void)ups_restore_host_env_json(getenv(UPS_HOST_ENV_KEY));_exit(126);
 }
 installed=1;char line[256];snprintf(line,sizeof line,"{\"event\":\"product_native_installed\",\"pid\":%ld,\"percent\":%u,\"policy_factor\":%.9g,\"native_installed\":true,\"actual_u_measured\":false,\"production_applied\":false,\"presented\":false}",(long)getpid(),policy.percent,policy.u);ns_log(line);
}
extern "C" void ns_before_menu(){
 if(owner)return;
 owner=tid();if(owner!=(long)getpid()||rb_bind_owner((uint64_t)owner))_exit(126);
 GdkDisplay*d=gdk_display_get_default();GtkSettings*s=gtk_settings_get_default();
 const char*dpi=getenv("GDK_DPI_SCALE");
 if(!d||!GDK_IS_X11_DISPLAY(d)||!s||(dpi&&strcmp(dpi,"1")&&strcmp(dpi,"1.0"))){
  dprintf(2,"Unity scaling: custom scaling requires GTK X11/G1 and neutral process DPI multiplier.\n");_exit(126);
 }
 // Process-local GTK setting only, once before the first menubar is created.
 int before=0,after=0,target=(int)lround(96.0*policy.u*1024.0);
 g_object_get(s,"gtk-xft-dpi",&before,nullptr);g_object_set(s,"gtk-xft-dpi",target,nullptr);g_object_get(s,"gtk-xft-dpi",&after,nullptr);
 if(after!=target)_exit(126);menu_dpi=target;
 char line[256];snprintf(line,sizeof line,"{\"event\":\"startup_gtk_dpi\",\"before\":%d,\"target\":%d,\"actual\":%d,\"owner_tid\":%ld}",before,target,after,owner);ns_log(line);
}
extern "C" void ns_menubar(void*p){
 if(bar)g_object_remove_weak_pointer(G_OBJECT(bar),(gpointer*)&bar);
 bar=GTK_WIDGET(p);if(!bar||gtk_widget_get_scale_factor(bar)!=1)_exit(126);
 g_object_add_weak_pointer(G_OBJECT(bar),(gpointer*)&bar);
 if(fd>=0&&main_thread()&&!diagnostic_configured){
  diagnostic_configured=true;
  const char*raw=getenv("UNITY_EDITOR_SCALING_DIAGNOSTIC_SAMPLES");
  if(raw){
   unsigned parsed=0;size_t length=strnlen(raw,4);bool valid=length>=1&&length<=3;
   for(size_t i=0;valid&&i<length;i++){if(raw[i]<'0'||raw[i]>'9')valid=false;else parsed=parsed*10+(unsigned)(raw[i]-'0');}
   if(valid&&parsed>=1&&parsed<=120)diagnostic_limit=parsed;
   else ns_log("{\"event\":\"startup_diagnostic_config_refused\",\"samples\":16,\"reason\":\"expected_integer_1_to_120\"}");
  }
 }
 const char*enabled=getenv("UNITY_EDITOR_SCALING_DIAGNOSTICS");
 if(fd>=0&&(!enabled||strcmp(enabled,"0"))&&!diagnostic_source&&!diagnostic_snapshots){
  GSource*s=g_timeout_source_new_seconds(1);g_source_set_priority(s,G_PRIORITY_DEFAULT);
  g_source_set_callback(s,diagnostics,nullptr,nullptr);diagnostic_source=g_source_attach(s,g_main_context_default());g_source_unref(s);
 }
}
extern "C" void v6_on_gui_begin(void*,void*){} // No runtime cache mutation/lease.
extern "C" uint64_t v6_main_handle(){
 if(!geometry_ready())return 0;
 void*entry=load<void*>((void*)(image+0x67ce468),0x158);if(!entry)return 0;
 uint64_t native=load<uint64_t>(entry,8);
 if(!native||!valid((void*)native)||!v6_birth_lookup(native,V6_BIRTH_WINDOW)||
    load<unsigned>((void*)native,0x40)!=4||load<unsigned char>((void*)native,0xc0)||load<unsigned char>((void*)native,0xc3))return 0;
 if(!bar||!GTK_IS_MENU_BAR(bar)||!gtk_widget_get_mapped(bar))return 0;return native;
}
extern "C" int v6_main_read(uint64_t native,float u,cg_sample*out){
 if(!out)return CG_ARGUMENT;*out={};if(native!=v6_main_handle())return CG_STALE;
 Read context{native,v6_birth_lookup(native,V6_BIRTH_WINDOW),v6_birth_generation()};
 cg_unity_context adapter{&context,admit,menu};cg_host host=cg_unity_host(&adapter);
 return cg_read(&host,native,context.generation,u,out);
}
extern "C" int v6_main_menu_height(uint64_t native,int*out){
 if(!out||native!=v6_main_handle())return CG_STALE;
 GtkAllocation a{};gtk_widget_get_allocation(bar,&a);if(a.height<1||gtk_widget_get_scale_factor(bar)!=1)return CG_CHART;*out=a.height;return 0;
}
extern "C" void v6_main_trace(unsigned source,const cg_sample*s,unsigned depth){
 if(fd>=0&&main_thread()&&s&&trace_rows++<256)dprintf(fd,"{\"event\":\"main_producer\",\"source\":%u,\"native\":\"0x%llx\",\"content_L\":[%d,%d,%d,%d],\"points\":[%.9g,%.9g,%.9g,%.9g],\"depth\":%u}\n",source,(unsigned long long)s->native,s->content_L.x,s->content_L.y,s->content_L.w,s->content_L.h,s->target_container_points[0],s->target_container_points[1],s->target_container_points[2],s->target_container_points[3],depth);
}
extern "C" int unity_native_startup_query(ns_status*out,uint32_t bytes){
 if(!out||bytes!=sizeof *out)return -1;*out={};out->abi=1;out->size=sizeof *out;
 if(tid()!=(long)getpid())return -2; // Reject before reading owner-thread GTK state.
 out->pid=getpid();out->owner_tid=owner;out->percent=policy.percent;out->installed=installed.load();
 out->menu_dpi=menu_dpi;out->menu_ready=bar!=nullptr;out->factor=(float)policy.u;
 return 0;
}
