#include "birth.h"
#include <sys/syscall.h>
#include <unistd.h>
namespace{
struct Row{uint64_t native,birth;unsigned kind,state;};Row rows[256]{};
uint64_t serial=1;bool poison;
bool owner(){return syscall(SYS_gettid)==getpid();}
Row *find(uint64_t p,unsigned k){for(auto&r:rows)if(r.native==p&&r.kind==k)return &r;return nullptr;}
}
extern "C" uint64_t v6_birth_begin(void*p,unsigned k){
 if(!owner()||!p||(k!=1&&k!=2)||serial==UINT64_MAX){poison=true;return 0;}
 Row*r=find((uint64_t)p,k);if(!r)for(auto&v:rows)if(!v.state){r=&v;break;}
 if(!r){poison=true;return 0;}
 *r={(uint64_t)p,++serial,k,1};return r->birth;
}
extern "C" void v6_birth_ready(void*p,unsigned k,uint64_t token){
 if(!owner()){poison=true;return;}Row*r=find((uint64_t)p,k);
 if(r&&r->birth==token&&r->state==1)r->state=2;
 // A destructor/replacement during native initialization must not resurrect it.
}
extern "C" void v6_birth_destroy(void*p,unsigned k){
 if(!owner()||serial==UINT64_MAX){poison=true;return;}++serial;
 Row*r=find((uint64_t)p,k);if(r)r->state=0;
}
extern "C" uint64_t v6_birth_lookup(uint64_t p,unsigned k){
 if(!owner()||poison)return 0;Row*r=find(p,k);return r&&r->state==2?r->birth:0;
}
extern "C" uint64_t v6_birth_generation(){return owner()&&!poison?serial:0;}
extern "C" int v6_birth_poisoned(){return poison||!owner();}
