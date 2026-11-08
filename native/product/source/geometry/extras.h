#pragma once
#include "review/scopes.h"
#ifdef __cplusplus
extern "C" {
#endif
int v6_extras_bind(uintptr_t image);
const v6_scope_candidate *v6_extras_candidates(size_t *count);
/* Called by generated V6 h_popup wrapper in place of old integer callback. */
void v6_precise_popup(void *menu,int*x,int*y,int*push,void *data);
#ifdef __cplusplus
}
#endif
