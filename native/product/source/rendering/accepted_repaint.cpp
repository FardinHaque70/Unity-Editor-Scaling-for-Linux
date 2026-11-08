#include "accepted_repaint.h"
#include "../geometry/birth.h"
#include "../startup.h"
#ifdef NSP_REPAINT_TESTING
#include "accepted_repaint_test_host.h"
#else
#include <gtk/gtk.h>
#endif
#include <sys/syscall.h>
#include <unistd.h>
#include <cstring>
#include <cstdio>

namespace {
uintptr_t image;
struct Watch {void*view;uint64_t birth;GWeakRef widget;gulong handler;bool used,observed;GtkAllocation last;};
Watch watches[256]{};
bool owner(){return image&&syscall(SYS_gettid)==getpid();}
template<class T>T load(void*p,unsigned off){T value;std::memcpy(&value,(char*)p+off,sizeof value);return value;}
void allocation(GtkWidget*widget,GtkAllocation*a,gpointer opaque) noexcept {
 // The signal owns widget for this emission. The native view is dereferenced
 // only after its independent birth token still matches. No GTK/GL event pump.
 try {
  auto*w=static_cast<Watch*>(opaque);
  if(!owner()||!w||!w->used||!w->handler||!a||a->width<1||a->height<1||
     v6_birth_lookup((uint64_t)w->view,V6_BIRTH_VIEW)!=w->birth)return;
  if(load<GtkWidget*>(w->view,0x10)!=widget||!gtk_widget_get_mapped(widget))return;
  void*gfx=load<void*>(w->view,0xf8);if(!gfx)return;
  if(w->observed&&w->last.x==a->x&&w->last.y==a->y&&w->last.width==a->width&&w->last.height==a->height)return;
  w->last=*a;w->observed=true;
  int width=load<int>(gfx,0x68),height=load<int>(gfx,0x6c);
  if(width==a->width&&height==a->height)return;
  // Exact native API queues a normal future Unity repaint (false), without
  // synchronous DoPaint/Reshape/managed callbacks inside GTK size allocation.
  bool queued=reinterpret_cast<bool(*)(void*,const void*,bool)>(image+0x3b335f0)(
      (void*)(image+0x67ce468),w->view,false);
  char line[320];std::snprintf(line,sizeof line,
   "{\"event\":\"accepted_allocation_repaint\",\"native\":\"0x%llx\",\"birth\":%llu,\"allocation_L\":[%d,%d,%d,%d],\"previous_backing\":[%d,%d],\"queued\":%s}",
   (unsigned long long)(uintptr_t)w->view,(unsigned long long)w->birth,a->x,a->y,a->width,a->height,width,height,queued?"true":"false");
  ns_log(line);
 }catch(...){ns_log("{\"event\":\"accepted_allocation_repaint_refused\",\"reason\":\"native_exception\"}");}
}
}
extern "C" void nsp_repaint_bind(uintptr_t base){image=base;}
extern "C" void nsp_repaint_detach(void*view){
 if(!owner())return;
 for(auto&w:watches)if(w.used&&w.view==view){
  // Mark inert before disconnect, so even a nested emission cannot use it.
  w.used=false;GObject*object=(GObject*)g_weak_ref_get(&w.widget);
  if(object){if(w.handler&&g_signal_handler_is_connected(object,w.handler))g_signal_handler_disconnect(object,w.handler);g_object_unref(object);}
  g_weak_ref_clear(&w.widget);w.handler=0;w.view=nullptr;w.birth=0;w.observed=false;
 }
}
extern "C" void nsp_repaint_attach(void*view,uint64_t expected_birth){
 if(!owner()||!view||!expected_birth||v6_birth_lookup((uint64_t)view,V6_BIRTH_VIEW)!=expected_birth)return;
 nsp_repaint_detach(view); // Also retire a watcher created by nested SetWindow.
 GtkWidget*widget=load<GtkWidget*>(view,0x10);
 if(!widget||!GTK_IS_WIDGET(widget))return;
 for(auto&w:watches)if(!w.used){
  w.view=view;w.birth=expected_birth;w.observed=false;w.used=true;
  g_weak_ref_init(&w.widget,G_OBJECT(widget));
  w.handler=g_signal_connect_data(widget,"size-allocate",G_CALLBACK(allocation),&w,nullptr,G_CONNECT_AFTER);
  if(!w.handler){w.used=false;g_weak_ref_clear(&w.widget);w.view=nullptr;w.birth=0;}
  return;
 }
 ns_log("{\"event\":\"accepted_allocation_repaint_refused\",\"reason\":\"watch_capacity\"}");
}
