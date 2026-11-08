#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Internal ABI, not IPC. Evidence bits are integration prerequisites, not proof. */
enum { EP_DEFAULT=0, EP_CUSTOM=1 };
enum { EP_INPUT=1, EP_LAYOUT=2, EP_RENDER=4, EP_MUTATION=8 };
enum { EP_OWNER=1, EP_FRAME=2, EP_QUEUE=4, EP_REGISTRY=8, EP_MANAGED=16,
       EP_MENU=32, EP_PLAYER=64, EP_IDENTITY=128, EP_ALL=255 };
enum { EP_OK=0, EP_BUSY=-1, EP_GATE=-2, EP_STALE=-3, EP_APPLY=-4,
       EP_POISON=-5, EP_RANGE=-6, EP_OWNER_ERROR=-7 };
typedef struct { uint64_t epoch, registry, queue; uint32_t mode, percent; double u; } ep_snapshot;
typedef struct { uint64_t key, birth; int x,y,w,h; } ep_raw_window;
/* All callbacks synchronous, GTK owner, MUST NOT pump GTK or wait for rendering.
 * prepare captures raw GTK client L, registry generation + object birth tokens.
 * apply performs the separate managed/native invalidation contract using `next`.
 * verify rereads GTK geometry/registry and checks cache/layout postconditions.
 * rollback MUST restore caches/menu/player policy + raw client geometry and verify.
 * No callback may dereference a retained native pointer without registry lookup
 * and birth-token validation. A raw pointer or registry contains() alone has ABA.
 */
typedef struct {
 int (*prepare)(const ep_snapshot*, const ep_snapshot*, void*);
 int (*apply)(const ep_snapshot*, void*);
 int (*verify)(const ep_snapshot*, void*);
 int (*rollback)(const ep_snapshot*, void*);
 void *data;
} ep_transition;
int ep_initialize(uint32_t mode, uint32_t percent); /* once on proven GTK owner */
int ep_begin(uint32_t operation, uint64_t queued_epoch, uint64_t registry);
void ep_end(void);
int ep_current(ep_snapshot*); /* succeeds ONLY inside a bound operation */
int ep_observe(ep_snapshot*); /* request-thread status; never use for conversion */
int ep_commit(uint32_t mode,uint32_t percent,uint32_t gates,uint64_t registry,
              uint64_t drained_queue, const ep_transition*);
int ep_registry_changed(void); /* owner lifecycle hook, invalidates pending work */
int ep_poisoned(void);
#ifdef __cplusplus
}
/* For wrapper-entry scope: requires an outer INPUT/LAYOUT/RENDER operation. */
struct ep_wrapper_scope {
 ep_snapshot value;
 ep_wrapper_scope();
 ~ep_wrapper_scope();
};
#endif
