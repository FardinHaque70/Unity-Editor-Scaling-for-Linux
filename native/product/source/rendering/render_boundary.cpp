#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "render_boundary.h"
#include "accepted_repaint.h"
#include "startup.h"
#include "geometry/birth.h"
extern "C" void v6_on_gui_begin(void*,void*);
#include <cstdlib>
extern "C" int rb_current_gui_scope(void);
#include <atomic>
#include <array>
#include <cstring>
#include <exception>
#include <vector>
#include <cstdio>
#include <cerrno>
#include <climits>
#include <dlfcn.h>
#include <link.h>
#include <openssl/evp.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace {
constexpr const char *hash="d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec";
struct Entry {const char*name;uintptr_t va;size_t len;unsigned char before[16];};
const Entry entries[]={
#include "entry_guards.h"
};
static_assert(sizeof(entries)/sizeof(*entries)==RB_OPERATION_COUNT,"operation ABI drift");
std::array<std::atomic<uint32_t>,RB_OPERATION_COUNT> active{};
std::array<std::atomic<uint64_t>,RB_OPERATION_COUNT> entered{},exited{};
std::atomic<uint64_t> serial{0},total{0},coverage{0},owner{0},gui_open{0},context_open{0};
std::atomic<uint32_t> poison{0},installed{0},bound{0};
std::atomic<uint64_t> owner_pid{0};
void *original[RB_OPERATION_COUNT]{};
char error[192]="not installed";
uint64_t tid(){static thread_local const uint64_t value=(uint64_t)syscall(SYS_gettid);return value;}
void fail(const char *s){std::snprintf(error,sizeof error,"%s",s);}
struct Scope {
 unsigned op;int exceptions;
 explicit Scope(unsigned id):op(id),exceptions(std::uncaught_exceptions()){
  if(owner.load(std::memory_order_acquire)&&owner.load()!=tid())poison.fetch_or(RB_FOREIGN_THREAD);
  active[op].fetch_add(1,std::memory_order_relaxed);total.fetch_add(1,std::memory_order_acq_rel);
  entered[op].fetch_add(1,std::memory_order_relaxed);serial.fetch_add(1,std::memory_order_release);
 }
 Scope(const Scope&)=delete;Scope&operator=(const Scope&)=delete;
 ~Scope() noexcept {
  if(std::uncaught_exceptions()>exceptions)poison.fetch_or(RB_EXCEPTION,std::memory_order_relaxed);
  exited[op].fetch_add(1,std::memory_order_relaxed);active[op].fetch_sub(1,std::memory_order_relaxed);
  total.fetch_sub(1,std::memory_order_acq_rel);serial.fetch_add(1,std::memory_order_release);
 }
};
/* Pointer values are identity keys only; never dereferenced later. Entry wrappers
 * do not retain ownership. A lost pair/destruction stays fail-closed. */
struct Pair {uintptr_t key=0,state=0;unsigned kind=0,count=0;};
std::array<Pair,128> pairs{};
void pair_change(void *object,unsigned kind,int delta,void *state=nullptr){
 if(owner.load()!=tid()){poison.fetch_or(RB_FOREIGN_THREAD);return;}
 auto &count=kind==1?gui_open:context_open;
 for(auto &p:pairs)if(p.key==(uintptr_t)object&&p.kind==kind&&p.count){
  if(p.state!=(uintptr_t)state){poison.fetch_or(RB_PAIR_MISMATCH);return;}
  if(delta>0){++p.count;count.fetch_add(1);}else{--p.count;count.fetch_sub(1);}
  serial.fetch_add(1,std::memory_order_release);return;
 }
 if(delta<0){poison.fetch_or(RB_PAIR_MISMATCH);return;}
 for(auto &p:pairs)if(!p.count){p={(uintptr_t)object,(uintptr_t)state,kind,1};count.fetch_add(1);serial.fetch_add(1,std::memory_order_release);return;}
 poison.fetch_or(RB_PAIR_OVERFLOW);
}
void lifetime_end(void *object){
 if(owner.load()!=tid()){poison.fetch_or(RB_FOREIGN_THREAD);return;}
 for(const auto &p:pairs)if(p.count&&p.key==(uintptr_t)object)poison.fetch_or(RB_PAIR_MISMATCH);
}
template<class T>T orig(unsigned id){return reinterpret_cast<T>(original[id]);}
struct Rect {float x,y,w,h;};
#define ONE(name,id) static void name(void*p){Scope s(id);orig<void(*)(void*)>(id)(p);}
#define TWO(name,id) static void name(void*p,void*q){Scope s(id);orig<void(*)(void*,void*)>(id)(p,q);}
#define BOOLARG(name,id) static void name(void*p,bool b){Scope s(id);orig<void(*)(void*,bool)>(id)(p,b);}
BOOLARG(paint,RB_PAINT)
ONE(reshape,RB_RESHAPE)
ONE(screen,RB_SCREEN)
ONE(create_gfx,RB_CREATE_GFX)
TWO(set_position,RB_SET_POSITION)
static void set_window(void*p,void*q){Scope s(RB_SET_WINDOW);auto birth=v6_birth_lookup((uint64_t)p,V6_BIRTH_VIEW);nsp_repaint_detach(p);orig<void(*)(void*,void*)>(RB_SET_WINDOW)(p,q);nsp_repaint_attach(p,birth);}
static void set_rect(void*p,const Rect*r,bool b){Scope s(RB_SET_RECT);orig<void(*)(void*,const Rect*,bool)>(RB_SET_RECT)(p,r,b);}
static void rect_changed(void*p,Rect r){Scope s(RB_RECT_CHANGED);orig<void(*)(void*,Rect)>(RB_RECT_CHANGED)(p,r);}
static bool process_input(void*p,void*e){Scope s(RB_PROCESS_INPUT);return orig<bool(*)(void*,void*)>(RB_PROCESS_INPUT)(p,e);}
static bool on_input(void*p,void*e){Scope s(RB_ON_INPUT);return orig<bool(*)(void*,void*)>(RB_ON_INPUT)(p,e);}
TWO(send_layout,RB_SEND_LAYOUT)
static void *begin_gui(void*p,void*e,void*k){Scope s(RB_BEGIN_GUI);void *r=orig<void*(*)(void*,void*,void*)>(RB_BEGIN_GUI)(p,e,k);pair_change(p,1,+1,r);v6_on_gui_begin(p,r);return r;}
static void end_gui(void*p,void*g,void*k){Scope s(RB_END_GUI);orig<void(*)(void*,void*,void*)>(RB_END_GUI)(p,g,k);pair_change(p,1,-1,g);}
static void begin_context(void*p){Scope s(RB_BEGIN_CONTEXT);void *gfx;std::memcpy(&gfx,(char*)p+0xf8,sizeof gfx);orig<void(*)(void*)>(RB_BEGIN_CONTEXT)(p);if(gfx)pair_change(p,2,+1,gfx);}
static void end_context(void*p,bool b){Scope s(RB_END_CONTEXT);void *gfx;std::memcpy(&gfx,(char*)p+0xf8,sizeof gfx);orig<void(*)(void*,bool)>(RB_END_CONTEXT)(p,b);if(gfx)pair_change(p,2,-1,gfx);}
static void view_dtor(void*p){Scope s(RB_VIEW_DTOR);nsp_repaint_detach(p);v6_birth_destroy(p,V6_BIRTH_VIEW);orig<void(*)(void*)>(RB_VIEW_DTOR)(p);lifetime_end(p);}
static void container_dtor(void*p){Scope s(RB_CONTAINER_DTOR);v6_birth_destroy(p,V6_BIRTH_WINDOW);orig<void(*)(void*)>(RB_CONTAINER_DTOR)(p);lifetime_end(p);}
static void view_ctor(void*p){Scope s(RB_VIEW_CTOR);auto t=v6_birth_begin(p,V6_BIRTH_VIEW);orig<void(*)(void*)>(RB_VIEW_CTOR)(p);v6_birth_ready(p,V6_BIRTH_VIEW,t);}
static void container_init(void*p,void*mono,Rect r,int mode,const void*min,const void*max,void*exception){Scope s(RB_CONTAINER_INIT);auto t=v6_birth_begin(p,V6_BIRTH_WINDOW);orig<void(*)(void*,void*,Rect,int,const void*,const void*,void*)>(RB_CONTAINER_INIT)(p,mono,r,mode,min,max,exception);v6_birth_ready(p,V6_BIRTH_WINDOW,t);}
BOOLARG(repaint_batch,RB_REPAINT_BATCH)
TWO(menu_allocate,RB_MENU_ALLOCATE)
TWO(container_allocate,RB_CONTAINER_ALLOCATE)
/* Exact x86_64 ABI adapters: WindowKey return is a hidden RDI pointer; the
 * unique_ptr argument is an invisible reference. Do not construct/copy/destroy
 * a replacement C++ owner. Only the original body consumes it. */
static void *add_view(void*out,void*manager,void*unique,void*exception){Scope s(RB_ADD_VIEW);return orig<void*(*)(void*,void*,void*,void*)>(RB_ADD_VIEW)(out,manager,unique,exception);}
static void *add_window(void*out,void*manager,void*unique,void*exception){Scope s(RB_ADD_WINDOW);return orig<void*(*)(void*,void*,void*,void*)>(RB_ADD_WINDOW)(out,manager,unique,exception);}
static bool remove_view(void*m,const void*key,void*e){Scope s(RB_REMOVE_VIEW);return orig<bool(*)(void*,const void*,void*)>(RB_REMOVE_VIEW)(m,key,e);}
static bool remove_window(void*m,const void*key,void*e){Scope s(RB_REMOVE_WINDOW);return orig<bool(*)(void*,const void*,void*)>(RB_REMOVE_WINDOW)(m,key,e);}
static void minmax(void*p,const void*a,const void*b){Scope s(RB_MINMAX);orig<void(*)(void*,const void*,const void*)>(RB_MINMAX)(p,a,b);}
static void recreate_context(void*p,int a,int b){Scope s(RB_RECREATE_CONTEXT);orig<void(*)(void*,int,int)>(RB_RECREATE_CONTEXT)(p,a,b);}
static void initialize_view(void*p,void*m,int a,int b,bool c,void*e){Scope s(RB_INITIALIZE_VIEW);orig<void(*)(void*,void*,int,int,bool,void*)>(RB_INITIALIZE_VIEW)(p,m,a,b,c,e);}
BOOLARG(pending_delete,RB_PENDING_DELETE)
ONE(make_modal,RB_MAKE_MODAL)
static void bring_live(void*p,bool a,bool b,bool c){Scope s(RB_BRING_LIVE);orig<void(*)(void*,bool,bool,bool)>(RB_BRING_LIVE)(p,a,b,c);}
void *replacement[]={ (void*)paint,(void*)reshape,(void*)screen,(void*)create_gfx,(void*)set_position,(void*)set_window,(void*)set_rect,(void*)rect_changed,(void*)process_input,(void*)on_input,(void*)send_layout,(void*)begin_gui,(void*)end_gui,(void*)begin_context,(void*)end_context,(void*)view_dtor,(void*)container_dtor,(void*)view_ctor,(void*)container_init,(void*)repaint_batch,(void*)menu_allocate,(void*)container_allocate,(void*)add_view,(void*)add_window,(void*)remove_view,(void*)remove_window,(void*)minmax,(void*)recreate_context,(void*)initialize_view,(void*)pending_delete,(void*)make_modal,(void*)bring_live };
static_assert(sizeof(replacement)/sizeof(*replacement)==RB_OPERATION_COUNT,"wrapper ABI drift");
static_assert(RB_OPERATION_COUNT<=32,"one-page trampoline capacity");
void jump_absolute(unsigned char *p,uintptr_t destination){const unsigned char op[]={0xff,0x25,0,0,0,0};std::memcpy(p,op,6);std::memcpy(p+6,&destination,8);}
struct Patch {unsigned id;unsigned char *entry;size_t len;unsigned char before[16];unsigned char after[16];};
/* Each slot: a14-byte branch thunk to wrapper and original prefix + absolute
 * jump to original+len. Copied instructions have NO calls/RIP refs/branches.
 * No exception can originate from an external call before the jump back to
 * Unity's ORIGINAL FDE, whose native prologue stack layout is reproduced. */
void *near_page(uintptr_t target){
 for(uintptr_t step=0;step<512;step++){
  uintptr_t at=((target+0x8000000+step*0x10000)&~uintptr_t(4095));
  void *p=mmap((void*)at,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
  if(p!=MAP_FAILED)return p;
 }
 return nullptr;
}
bool apply(std::vector<Patch>&plans){
 if(plans.empty())return false;
 void *memory=near_page((uintptr_t)plans[0].entry);if(!memory){fail("no nearby trampoline page");return false;}
 auto *arena=(unsigned char*)memory;
 for(size_t j=0;j<plans.size();j++){
  auto &p=plans[j];auto *slot=arena+j*128;intptr_t displacement=(intptr_t)slot-((intptr_t)p.entry+5);
  if(displacement<INT32_MIN||displacement>INT32_MAX){munmap(memory,4096);fail("relative branch out of range");return false;}
  jump_absolute(slot,(uintptr_t)replacement[p.id]);
  std::memcpy(slot+32,p.before,p.len);jump_absolute(slot+32+p.len,(uintptr_t)p.entry+p.len);
  original[p.id]=slot+32;
  std::memset(p.after,0x90,p.len);p.after[0]=0xe9;int32_t rel=(int32_t)displacement;std::memcpy(p.after+1,&rel,4);
 }
 if(mprotect(memory,4096,PROT_READ|PROT_EXEC)){munmap(memory,4096);fail("trampoline RX failed");return false;}
 std::vector<uintptr_t> pages;
 for(const auto&p:plans)for(uintptr_t a=(uintptr_t)p.entry&~uintptr_t(4095);a<(uintptr_t)p.entry+p.len;a+=4096){bool seen=false;for(auto old:pages)if(old==a)seen=true;if(!seen)pages.push_back(a);}
 size_t writable=0;
 for(auto p:pages){if(mprotect((void*)p,4096,PROT_READ|PROT_WRITE|PROT_EXEC)){
   for(size_t j=0;j<writable;j++)if(mprotect((void*)pages[j],4096,PROT_READ|PROT_EXEC))_exit(126);
   munmap(memory,4096);fail("entry writable protection failed before install");return false;
  }++writable;}
 for(const auto&p:plans)std::memcpy(p.entry,p.after,p.len);
 for(auto p:pages)if(mprotect((void*)p,4096,PROT_READ|PROT_EXEC)){
  /* Cannot safely continue a partially protected/installed launch. */
  poison.fetch_or(RB_PARTIAL_INSTALL);_exit(126);
 }
 for(const auto&p:plans)coverage.fetch_or(UINT64_C(1)<<p.id);
 owner_pid.store((uint64_t)getpid());installed.store(1,std::memory_order_release);fail("ok");return true;
}
bool own_hash(){
 FILE*f=std::fopen("/proc/self/exe","rb");if(!f)return false;
 EVP_MD_CTX*c=EVP_MD_CTX_new();if(!c){std::fclose(f);return false;}
 bool ok=EVP_DigestInit_ex(c,EVP_sha256(),nullptr)==1;unsigned char buf[65536],digest[32]{};unsigned n=0;size_t got;
 while(ok&&(got=std::fread(buf,1,sizeof buf,f)))ok=EVP_DigestUpdate(c,buf,got)==1;
 ok=ok&&!std::ferror(f)&&EVP_DigestFinal_ex(c,digest,&n)==1&&n==32;
 EVP_MD_CTX_free(c);std::fclose(f);char hex[65];for(unsigned j=0;j<32;j++)std::snprintf(hex+j*2,3,"%02x",digest[j]);hex[64]=0;
 return ok&&!std::strcmp(hex,hash);
}
}
extern "C" int rb_install_launch_only(uintptr_t base){
 if(installed.load()){fail("already installed");return -1;}
 char exe[4096];ssize_t n=readlink("/proc/self/exe",exe,sizeof exe-1);if(n<0)return -1;exe[n]=0;
 int role=rb_current_gui_scope();if(role==1||role==0)return 1;
 if(role!=2||tid()!=(uint64_t)getpid()){fail("GUI main-thread launch only");return -1;}
 if(ns_percent()<100||ns_percent()>200){fail("admitted product custom profile required");return -1;}
 if(!base||sysconf(_SC_PAGESIZE)!=4096||!own_hash()){fail("unsupported executable/build/page");return -1;}
 struct Match{uintptr_t base;bool found;};Match match{base,false};
 dl_iterate_phdr([](dl_phdr_info*i,size_t,void*p)->int{auto*m=(Match*)p;if((!i->dlpi_name||!*i->dlpi_name)&&(uintptr_t)i->dlpi_addr==m->base)m->found=true;return 0;},&match);
 if(!match.found){fail("not main ELF load base");return -1;}
 /* Before any Application object exists: rejects live installation even if
  * an outside caller guesses the exact image base and flag. */
 if(*(void**)(base+0x67b3948)){fail("Application already exists; launch-only observer");return -1;}
 try{
  std::vector<Patch> plans;plans.reserve(RB_OPERATION_COUNT);
  for(unsigned j=0;j<RB_OPERATION_COUNT;j++){
   const auto&e=entries[j];auto*p=(unsigned char*)(base+e.va);
   if(std::memcmp(p,e.before,e.len)){fail("entry prefix differs");return -1;}
   Patch x{};x.id=j;x.entry=p;x.len=e.len;std::memcpy(x.before,e.before,e.len);plans.push_back(x);
  }
  owner.store(tid());return apply(plans)?0:-1;
 }catch(...){fail("allocation exception before patch preparation");return -1;}
}
extern "C" int rb_bind_owner(uint64_t who){
 if(!installed.load()||who!=tid()||who!=(uint64_t)getpid()||owner.load()!=who){fail("owner bind requires verified main callback");return -1;}bound.store(1,std::memory_order_release);return 0;
}
extern "C" int rb_query(rb_snapshot*out){
 if(!out||out->size!=sizeof(*out)||out->version!=RB_ABI_VERSION)return -1;
 rb_snapshot s{};s.size=sizeof s;s.version=RB_ABI_VERSION;
 auto before=serial.load(std::memory_order_acquire);
 s.installed=installed.load(std::memory_order_acquire);s.coverage_mask=coverage.load();s.owner_tid=owner.load();s.caller_tid=tid();s.owner_matches=s.owner_tid==s.caller_tid&&owner_pid.load()==(uint64_t)getpid();
 s.active_total=total.load(std::memory_order_acquire);s.gui_pairs=gui_open.load();s.context_pairs=context_open.load();
 for(unsigned j=0;j<RB_OPERATION_COUNT;j++){s.active[j]=active[j].load();s.entered[j]=entered[j].load();s.exited[j]=exited[j].load();}
 s.poison=poison.load();s.owner_bound=bound.load(std::memory_order_acquire);s.serial=serial.load(std::memory_order_acquire);
 s.native_quiescent=s.installed&&s.owner_bound&&s.owner_matches&&!s.poison&&!s.active_total&&!s.gui_pairs&&!s.context_pairs&&before==s.serial&&s.coverage_mask==((UINT64_C(1)<<RB_OPERATION_COUNT)-1);
 /* Zero init deliberately leaves worker_drained/gpu_completed/presented false. */
 *out=s;return before==s.serial?0:1;
}
extern "C" const char *rb_last_error(){return error;}
#ifdef RB_TESTING
extern "C" int rb_test_install(unsigned id,void*fn,const unsigned char*prefix,size_t len){
 if(id>=RB_OPERATION_COUNT||len<5||len>16||std::memcmp(fn,prefix,len))return -1;
 Patch p{};p.id=id;p.entry=(unsigned char*)fn;p.len=len;std::memcpy(p.before,prefix,len);
 std::vector<Patch> plans{p};owner.store(tid());return apply(plans)?0:-1;
}
extern "C" void rb_test_reset(){
 for(unsigned j=0;j<RB_OPERATION_COUNT;j++){active[j]=0;entered[j]=0;exited[j]=0;}total=0;serial=0;poison=0;gui_open=0;context_open=0;for(auto&p:pairs)p={};
}
#endif
