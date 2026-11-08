#pragma once
#include "accepted_content.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
 void*owner_context;
 /* Trusted V6 owner implements real readiness/domain/registry/generation gate;
  * this helper never grants or fabricates a transition lease. */
 int(*admit)(void*,uint64_t native,uint64_t generation);
 void*(*main_menubar)(void*,uint64_t native);
} cg_unity_context;
/* Process-internal callback constructor; no global/retained Unity identities. */
cg_host cg_unity_host(cg_unity_context*);
#ifdef __cplusplus
}
#endif
