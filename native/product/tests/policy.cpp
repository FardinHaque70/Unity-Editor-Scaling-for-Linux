#include "startup.h"
#include "config.generated.h"
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
int main(int argc,char**argv){
 assert(argc==3);int rc=ns_initialize();
 if(!strcmp(argv[1],"refuse")){assert(rc<0);ep_snapshot s;assert(v6_conversion_snapshot(&s)==EP_GATE);return 0;}
 ep_snapshot s;assert(!v6_conversion_snapshot(&s));const bool custom=!strcmp(argv[1],"custom");
 assert(rc==(custom?1:0)&&s.mode==(custom?EP_CUSTOM:EP_DEFAULT));
 unsigned p=atoi(argv[2]);assert(s.percent==p&&s.u==(custom?(double)(float)(p/100.0):0));
 ns_status status{};assert(!unity_native_startup_query(&status,sizeof status));
 assert(status.factor==(float)s.u&&status.percent==p&&!status.installed&&!status.production_applied&&!status.presented);
 if(custom&&p==160){std::thread other([]{ns_status rejected{};rejected.percent=999;
  assert(unity_native_startup_query(&rejected,sizeof rejected)==-2&&rejected.percent==0&&rejected.owner_tid==0&&rejected.menu_ready==0);});other.join();}
 // This is a test-owned settings path, never the app's real preferences.
 FILE*f=fopen(NS_SETTINGS_FILE,"w");assert(f);fputs("{bad changed after initial read",f);fclose(f);
 assert(ns_initialize()==-1);ep_snapshot again;assert(!v6_conversion_snapshot(&again)&&again.u==s.u&&again.percent==s.percent);
}
