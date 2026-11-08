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
#define NS_SETTLED_ABI 1u
#define NS_MAX_WINDOWS 32u
#define NS_MAX_VIEWS 128u
typedef struct {uint64_t native,birth;uint32_t mode,reserved;int32_t client_L[4];float cached_P[4];} ns_window_sample;
typedef struct {uint64_t native,birth;int32_t allocation_L[4],backing[2];float cached_U;int32_t gtk_scale;} ns_view_sample;
typedef struct {
 uint32_t abi,size,window_count,view_count;uint64_t owner_tid,birth_generation,boundary_serial;
 uint32_t production_applied,presented,reserved[2];
 ns_window_sample windows[NS_MAX_WINDOWS];ns_view_sample views[NS_MAX_VIEWS];
} ns_settled_snapshot;
/* Read-only and synchronous. Call on the verified owner thread at a settled
 * native callback boundary; no timer, event pump, setters or GPU/present claim.
 * 0 success, -1 ABI, -2 thread, -3 not settled, -4 capacity/stale/exception.
 * Failures clear output, so partial rows can never be mistaken for evidence. */
__attribute__((visibility("default"))) int unity_native_settled_query(ns_settled_snapshot*,uint32_t);

#ifdef __cplusplus
}
#endif
