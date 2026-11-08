#include "accepted_repaint_test_host.h"
#include "rendering/accepted_repaint.h"
#include <cassert>
#include <cstring>
#include <thread>
#include <sys/mman.h>
#include <cstdint>
#include <cstdio>
static void*view;static uint64_t birth=7;static bool alive=true,mapped=true;
static unsigned queued,logs;static void*expected;
extern "C" uint64_t v6_birth_lookup(uint64_t pointer,unsigned kind){return pointer==(uint64_t)view&&kind==1&&alive?birth:0;}
extern "C" gboolean gtk_widget_get_mapped(GtkWidget*){return mapped;}
extern "C" void ns_log(const char*){++logs;}
static bool enqueue(void*,const void*p,bool immediate){assert(p==expected&&!immediate);++queued;return true;}
template<class T>void field(void*p,unsigned offset,T value){std::memcpy((char*)p+offset,&value,sizeof value);}
int main(){
 auto signal=g_signal_new("size-allocate",G_TYPE_OBJECT,G_SIGNAL_RUN_LAST,0,nullptr,nullptr,nullptr,G_TYPE_NONE,1,G_TYPE_POINTER);assert(signal);
 view=mmap(nullptr,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(view!=MAP_FAILED);expected=view;
 unsigned char gfx[128]{};field(gfx,0x68,1090);field(gfx,0x6c,781);field(view,0xf8,(void*)gfx);
 auto*widget=(GtkWidget*)g_object_new(G_TYPE_OBJECT,nullptr);field(view,0x10,widget);
 nsp_repaint_bind((uintptr_t)enqueue-0x3b335f0);nsp_repaint_attach(view,birth);
 auto emit=[&](GtkWidget*w,int x,int width,int height){GtkAllocation a{x,0,width,height};g_signal_emit(w,signal,0,&a);};
 emit(widget,0,800,682);assert(queued==1&&logs==1);
 emit(widget,0,800,682);assert(queued==1); // Repeated actual tuple cannot loop.
 emit(widget,1,800,682);assert(queued==2);
 field(gfx,0x68,800);field(gfx,0x6c,682);emit(widget,0,800,682);assert(queued==2);
 std::thread foreign([&]{emit(widget,0,900,682);});foreign.join();assert(queued==2);
 mapped=false;emit(widget,0,900,682);assert(queued==2);mapped=true;emit(widget,0,900,682);assert(queued==3);
 auto*replacement=(GtkWidget*)g_object_new(G_TYPE_OBJECT,nullptr);field(view,0x10,replacement);emit(widget,0,910,682);assert(queued==3);
 // Independently retired native memory must not be dereferenced by old signal.
 alive=false;assert(!mprotect(view,4096,PROT_NONE));emit(widget,0,920,682);assert(queued==3);assert(!mprotect(view,4096,PROT_READ|PROT_WRITE));alive=true;
 nsp_repaint_detach(view);emit(widget,0,930,682);assert(queued==3);g_object_unref(widget);
 nsp_repaint_attach(view,birth);emit(replacement,0,900,682);assert(queued==4);
 ++birth;emit(replacement,0,950,682);assert(queued==4); // Address reuse rejects old birth.
 nsp_repaint_detach(view);nsp_repaint_attach(view,birth);emit(replacement,0,950,682);assert(queued==5);
 g_object_unref(replacement);nsp_repaint_detach(view); // Weak destruction safely clears dead widget.
 assert(!munmap(view,4096));puts("{\"real_GObject_signals\":true,\"queued_only\":true,\"duplicate_tuple_suppressed\":true,\"native_retirement_PROT_NONE\":true,\"widget_identity\":true,\"weak_destruction\":true,\"foreign_thread\":true,\"birth_reuse\":true,\"Unity_run\":false}");
}
