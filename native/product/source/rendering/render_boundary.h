#ifndef UNITY_RENDER_BOUNDARY_H
#define UNITY_RENDER_BOUNDARY_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
#define RB_ABI_VERSION 1u
/* IDs map one-to-one to exact native entry guards in boundary_manifest.json. */
enum rb_operation {
 RB_PAINT, RB_RESHAPE, RB_SCREEN, RB_CREATE_GFX, RB_SET_POSITION,
 RB_SET_WINDOW, RB_SET_RECT, RB_RECT_CHANGED, RB_PROCESS_INPUT, RB_ON_INPUT,
 RB_SEND_LAYOUT, RB_BEGIN_GUI, RB_END_GUI, RB_BEGIN_CONTEXT, RB_END_CONTEXT,
 RB_VIEW_DTOR, RB_CONTAINER_DTOR, RB_VIEW_CTOR, RB_CONTAINER_INIT,
 RB_REPAINT_BATCH, RB_MENU_ALLOCATE, RB_CONTAINER_ALLOCATE,
 RB_ADD_VIEW, RB_ADD_WINDOW, RB_REMOVE_VIEW, RB_REMOVE_WINDOW,
 RB_MINMAX, RB_RECREATE_CONTEXT, RB_INITIALIZE_VIEW, RB_PENDING_DELETE,
 RB_MAKE_MODAL, RB_BRING_LIVE, RB_OPERATION_COUNT
};
enum rb_poison { RB_FOREIGN_THREAD=1, RB_EXCEPTION=2, RB_PAIR_OVERFLOW=4,
 RB_PAIR_MISMATCH=8, RB_PARTIAL_INSTALL=16 };
struct rb_snapshot {
 uint32_t size,version,installed,owner_matches;
 uint64_t coverage_mask,serial,active_total,gui_pairs,context_pairs;
 uint64_t entered[RB_OPERATION_COUNT],exited[RB_OPERATION_COUNT];
 uint32_t active[RB_OPERATION_COUNT];
 uint32_t poison,owner_bound;
 uint64_t owner_tid,caller_tid;
 /* Quiescent is ONLY native callback/pair exclusion. Never a GPU/present fact. */
 uint32_t native_quiescent,worker_drained,gpu_completed,presented;
};
/* Constructor/launch only: must run on process main thread, before Application
 * initialized, with original /proc/self/exe hash, all entry bytes intact.
 * No constructor or automatic runtime attach in this module. */
int rb_install_launch_only(uintptr_t image_base);
/* The captain calls this from its already verified GTK owner callback. */
int rb_bind_owner(uint64_t owner_tid);
/* Cheap query: no GTK, object dereference, queue wait, logging or event pump.
 * Caller supplies size/version. Does not acquire a mutation/presentation lease. */
int rb_query(struct rb_snapshot *out);
const char *rb_last_error(void);
#ifdef RB_TESTING
/* These symbols are compiled ONLY into the synthetic ABI test executable. */
int rb_test_install(unsigned id,void *entry,const unsigned char *prefix,size_t len);
void rb_test_reset(void);
#endif
#ifdef __cplusplus
}
#endif
#endif
