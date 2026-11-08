#pragma once
#include "v6_epoch_bridge.h"
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* No setter: this policy is initialized once, before any native patch. */
int ns_initialize(void); /*1CUSTOM,0DEFAULT,-1invalid*/
void ns_bootstrap(uintptr_t);
void ns_installed(void);
void ns_refused(const char*);
void ns_before_menu(void);
void ns_menubar(void*);
void ns_log(const char*);
unsigned ns_percent(void);
typedef struct {
 uint32_t abi,size;uint64_t pid,owner_tid;
 uint32_t percent,installed,menu_dpi,menu_ready;
 float factor;uint32_t production_applied,presented,reserved;
} ns_status;
__attribute__((visibility("default"))) int unity_native_startup_query(ns_status*,uint32_t);
#ifdef __cplusplus
}
#endif
