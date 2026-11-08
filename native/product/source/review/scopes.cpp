#include "scopes.h"
#include <atomic>
#include <exception>
namespace {
v6_scope_callbacks callbacks{};
bool attached;
thread_local unsigned nesting;
struct Stats {std::atomic<uint64_t> begins{0},ends{0},unwinds{0};std::atomic<unsigned> max_depth{0};};
Stats stats[8];
struct Scope {
 unsigned operation,site,level;uint64_t token;int exceptions;
 Scope(unsigned op,unsigned index,void *subject,const void *event):operation(op),site(index),level(++nesting),token(0),exceptions(std::uncaught_exceptions()) {
  Stats &s=stats[site];s.begins.fetch_add(1,std::memory_order_relaxed);
  unsigned old=s.max_depth.load(std::memory_order_relaxed);while(old<level&&!s.max_depth.compare_exchange_weak(old,level,std::memory_order_relaxed)){}
  if(callbacks.enter)token=callbacks.enter(operation,site,subject,event,level);
 }
 ~Scope() {
  bool unwind=std::uncaught_exceptions()>exceptions;
  if(callbacks.leave)callbacks.leave(token,operation,site,level,unwind);
  stats[site].ends.fetch_add(1,std::memory_order_relaxed);
  if(unwind)stats[site].unwinds.fetch_add(1,std::memory_order_relaxed);
  --nesting;
 }
};
/* Register-transport return declarations preserve every EAX bit for GTK and
 * GUIView input callbacks; callers consume AL or EAX. They do not assert an
 * unavailable source-level C++ return typedef. No RAX-hidden sret is present. */
using Input=uint32_t(*)(void*,void*);
Input original_press,original_release,original_motion,original_process,original_configure;
using SetRect=void(*)(void*,const float*,uint8_t);
SetRect original_setrect;
using SetPosition=void(*)(void*,const float*);
SetPosition original_setposition;
using Allocate=void(*)(void*,void*);
Allocate original_allocate;
uint32_t h_press(void *v,void *e){Scope s(V6_SCOPE_RAW_INPUT,0,v,e);return original_press(v,e);}
uint32_t h_release(void *v,void *e){Scope s(V6_SCOPE_RAW_INPUT,1,v,e);return original_release(v,e);}
uint32_t h_motion(void *v,void *e){Scope s(V6_SCOPE_RAW_INPUT,2,v,e);return original_motion(v,e);}
uint32_t h_process(void *v,void *e){Scope s(V6_SCOPE_INPUT_DISPATCH,3,v,e);return original_process(v,e);}
void h_setrect(void *c,const float *r,uint8_t fit){Scope s(V6_SCOPE_LAYOUT,4,c,r);original_setrect(c,r,fit);}
void h_setposition(void *v,const float *r){Scope s(V6_SCOPE_LAYOUT,5,v,r);original_setposition(v,r);}
uint32_t h_configure(void *c,void *e){Scope s(V6_SCOPE_LAYOUT,6,c,e);return original_configure(c,e);}
void h_allocate(void *c,void *r){Scope s(V6_SCOPE_LAYOUT,7,c,r);original_allocate(c,r);}
const v6_scope_candidate candidates[]={
#include "scope-recipes.generated.h"
};
}
extern "C" int v6_scope_attach_callbacks(const v6_scope_callbacks *p){if(attached||!p)return -1;callbacks=*p;attached=true;return 0;}
extern "C" const v6_scope_candidate *v6_scope_candidates(size_t *count){if(count)*count=sizeof(candidates)/sizeof(*candidates);return candidates;}
extern "C" unsigned v6_scope_current_depth(){return nesting;}
extern "C" int v6_scope_stats(unsigned site,v6_scope_statistics *out){if(site>=8||!out)return -1;Stats &s=stats[site];*out={s.begins.load(),s.ends.load(),s.unwinds.load(),s.max_depth.load()};return 0;}
