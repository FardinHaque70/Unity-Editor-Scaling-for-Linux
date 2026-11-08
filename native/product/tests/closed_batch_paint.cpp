// Host-only dispatch/lifetime regression. No Unity, GTK or GL execution.
#define RB_TESTING
#include "rendering/render_boundary.cpp"
#include <iostream>
#include <stdexcept>
#include <string>
extern "C" void v6_on_gui_begin(void*,void*){}
extern "C" int rb_current_gui_scope(){return 2;}
extern "C" unsigned ns_percent(){return 150;}
extern "C" void nsp_repaint_detach(void*){}
extern "C" void nsp_repaint_attach(void*,uint64_t){}
extern "C" void v6_birth_destroy(void*,unsigned){}
extern "C" uint64_t v6_birth_begin(void*,unsigned){return 1;}
extern "C" void v6_birth_ready(void*,unsigned,uint64_t){}
extern "C" uint64_t v6_birth_lookup(uint64_t,unsigned){return 1;}

namespace fixture {
struct View {alignas(void*) unsigned char memory[0x100]{};};
std::vector<void*> cached,painted;
std::vector<bool> forwarded;
void *close_trigger=nullptr,*close_target=nullptr,*nested_trigger=nullptr;
std::vector<void*> nested;
unsigned checks=0;
void check(bool passed,const char*message){++checks;if(!passed)throw std::runtime_error(message);}
void state(void*p,unsigned char closed,void*widget){
 std::memcpy((char*)p+0x2b,&closed,sizeof closed);
 std::memcpy((char*)p+0x10,&widget,sizeof widget);
}
void stock_paint(void*p,bool flag){
 painted.push_back(p);forwarded.push_back(flag);
 if(p==close_trigger&&close_target)state(close_target,1,nullptr);
 if(p==nested_trigger)for(auto*view:nested)paint(view,true);
}
void stock_batch(void*,bool flag){
 // Reproduce the native hazard: cached B remains in this local batch after A
 // closes it, so only the guarded DoPaint boundary can stop its stale paint.
 const auto local=cached;
 for(auto*p:local)paint(p,flag);
}
void reset(){
 rb_test_reset();owner.store((uint64_t)getpid());owner_pid.store((uint64_t)getpid());
 installed=1;bound=1;coverage=(UINT64_C(1)<<RB_OPERATION_COUNT)-1;
 original[RB_PAINT]=(void*)stock_paint;original[RB_REPAINT_BATCH]=(void*)stock_batch;
 cached.clear();painted.clear();forwarded.clear();nested.clear();close_trigger=close_target=nested_trigger=nullptr;
}
void balanced(unsigned expected_paints,unsigned expected_batches){
 rb_snapshot result{};result.size=sizeof result;result.version=RB_ABI_VERSION;
 check(rb_query(&result)==0,"snapshot query failed");
 check(result.poison==0,"unexpected boundary poison");
 check(result.active_total==0&&result.gui_pairs==0&&result.context_pairs==0,"boundary/pair leaked");
 check(result.entered[RB_PAINT]==expected_paints&&result.exited[RB_PAINT]==expected_paints,"paint scope imbalance");
 check(result.entered[RB_REPAINT_BATCH]==expected_batches&&result.exited[RB_REPAINT_BATCH]==expected_batches,"batch scope imbalance");
 check(result.native_quiescent==1,"completed host batch not quiescent");
}
void closing_b(){
 reset();View a,b,c;
 state(&a,0,(void*)1);state(&b,0,(void*)2);state(&c,0,(void*)3);
 cached={&a,&b,&c};close_trigger=&a;close_target=&b;
 repaint_batch(nullptr,true);
 check(painted.size()==2,"closed cached B reached original DoPaint");
 check(painted[0]==&a&&painted[1]==&c,"live batch views reordered or dropped");
 check(forwarded.size()==2&&forwarded[0]&&forwarded[1],"paint bool argument changed");
 balanced(3,1); // The skipped B still has a balanced observer scope.
}
void live_and_preview(){
 reset();View active,preview,other_flag;
 state(&active,1,(void*)1);state(&preview,0,nullptr);state(&other_flag,2,nullptr);
 cached={&active,&preview,&other_flag};repaint_batch(nullptr,false);
 check(painted.size()==3,"valid, flag0 preview or non1 flag was incorrectly blocked");
 check(painted[0]==&active&&painted[1]==&preview&&painted[2]==&other_flag,"forwarded view identity changed");
 check(!forwarded[0]&&!forwarded[1]&&!forwarded[2],"false bool argument changed");
 balanced(3,1);
}
void nested_inside_batch(){
 reset();View caller,preview,active,closed;
 state(&caller,0,(void*)1);state(&preview,0,nullptr);
 state(&active,1,(void*)2);state(&closed,1,nullptr);
 cached={&caller};nested_trigger=&caller;nested={&preview,&active,&closed};
 repaint_batch(nullptr,false);
 check(painted.size()==3,"nested fully closed paint was not skipped or valid preview was blocked");
 check(painted[0]==&caller&&painted[1]==&preview&&painted[2]==&active,"nested valid paint identity changed");
 check(!forwarded[0]&&forwarded[1]&&forwarded[2],"nested bool argument changed");
 balanced(4,1); // Nested direct calls share the enclosing batch predicate.
}
void direct_unchanged(){
 reset();View closed;state(&closed,1,nullptr);
 paint(&closed,true);
 check(painted.size()==1&&painted[0]==&closed,"direct paint outside batch was changed");
 check(forwarded[0],"direct paint bool changed");
 balanced(1,0);
}
}
int main(){
 try{
  fixture::closing_b();fixture::live_and_preview();fixture::nested_inside_batch();fixture::direct_unchanged();
  std::cout<<"{\"status\":\"PASS\",\"scope\":\"host dispatch only; no Unity/GTK/GL\",\"scenarios\":4,\"checks\":"<<fixture::checks<<"}\n";
  return 0;
 }catch(const std::exception&error){
  std::cerr<<"{\"status\":\"FAIL\",\"scope\":\"host dispatch only\",\"error\":\""<<error.what()<<"\"}\n";
  return 1;
 }
}
