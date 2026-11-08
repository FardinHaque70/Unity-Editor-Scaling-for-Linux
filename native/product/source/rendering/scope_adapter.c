#define _GNU_SOURCE
#include "../deps/native_scope_guard.h"
/* Keep the existing C implementation unmodified and compiled as C. */
int rb_current_gui_scope(void){
 char exe[4096];ssize_t n=readlink("/proc/self/exe",exe,sizeof exe-1);
 if(n<0||(size_t)n>=sizeof exe-1)return USG_ERROR;
 exe[n]=0;return (int)usg_current_scope(exe).scope;
}
