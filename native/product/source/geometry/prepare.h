#pragma once
#include "geometry.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {const char *name;uintptr_t va;size_t len;} v6g_range;
typedef struct {vg_patch patches[4];size_t count;} v6g_plan;
/* Root-only PREPARE, no target writes/mprotect/launch. Existing intervals must
 * include displaced ORIGINAL spans as well as actual entry/block write spans.
 * Invoke AFTER exact original SHA/role/base checks, BEFORE rb_install_launch_only
 * (which writes entries). Host callbacks must be REAL GTK, not Unity wrappers.
 * Successful prepare binds peer helper once. Any later launch error must fail
 * closed; never retry/rebind in a live Editor. Caller owns final patch writes. */
int v6g_prepare(uintptr_t image,const vg_host*,const v6g_range*,size_t,v6g_plan*);

#ifdef __cplusplus
}
#endif
