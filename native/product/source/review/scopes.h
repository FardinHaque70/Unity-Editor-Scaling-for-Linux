#pragma once
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
enum { V6_SCOPE_RAW_INPUT=1,V6_SCOPE_INPUT_DISPATCH=2,V6_SCOPE_LAYOUT=3 };
typedef struct {
 unsigned offset,width,end; uintptr_t target;
} v6_scope_reloc;
typedef struct {
 const char *name;uintptr_t va;unsigned displaced;unsigned char before[32];
 void *replacement;void **original;unsigned reloc_count;v6_scope_reloc reloc[2];
 unsigned operation;
} v6_scope_candidate;
typedef struct {
 /* Callbacks are internal, attached once BEFORE native entry installation.
  * They must not throw, pump GTK, invoke Unity or mutate scale. token is opaque;
  * zero is allowed for count-only use. queued work is NOT tagged here. */
 uint64_t (*enter)(unsigned operation,unsigned site,void *subject,const void *event,unsigned nesting);
 void (*leave)(uint64_t token,unsigned operation,unsigned site,unsigned nesting,int unwinding);
} v6_scope_callbacks;
int v6_scope_attach_callbacks(const v6_scope_callbacks*);
const v6_scope_candidate *v6_scope_candidates(size_t *count);
unsigned v6_scope_current_depth(void);
typedef struct {uint64_t begins,ends,unwinds;unsigned max_depth;} v6_scope_statistics;
int v6_scope_stats(unsigned site,v6_scope_statistics*);
#ifdef __cplusplus
}
#endif
