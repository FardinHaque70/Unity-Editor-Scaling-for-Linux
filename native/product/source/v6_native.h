#ifndef UNITY_V6_NATIVE_H
#define UNITY_V6_NATIVE_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
#define V6_ABI 1u
#define V6_VISIBLE __attribute__((visibility("default")))
enum { V6_INPUT=1, V6_LAYOUT=2, V6_RENDER=3 };
enum { V6_OK=0,V6_UNSUPPORTED=-1,V6_WRONG_OWNER=-2,V6_NOT_READY=-3,V6_BLOCKED=-4,V6_STALE=-5 };
enum { V6_MISSING_INPUT=1,V6_MISSING_LAYOUT=2,V6_MISSING_FRAME_FENCE=4,
 V6_MISSING_QUEUE=8,V6_MISSING_LIFECYCLE=16,V6_MISSING_MANAGED=32,
 V6_MISSING_NATIVE_CACHE=64,V6_MISSING_MENU=128,V6_MISSING_ACCEPTED_ROOT=256 };
/* Fixed-width low-frequency ABI; native pointers use uint64_t at this exactx64 build.
 * Query observes real native state. It does not grant a prepared epoch lease.
 * Fresh launch mode CUSTOM150 only; request always blocked in this candidate. */
typedef struct {
 uint32_t abi,size;uint64_t epoch,registry;uint32_t mode,percent;
 int64_t pid,owner_tid,calling_tid;uint32_t installed,owner_ready,context_owner;
 uint32_t live_commit_enabled,missing_gates,raw_gtk_g,reserved;
 uint64_t owner_ticks,snapshots,wrapper_unbound,operation_entries[3],operation_exits[3];
 uint32_t active_operations[3],peak_operations[3];
} v6_status;
typedef struct {
 uint32_t abi,size;uint64_t domain_cookie,request_cookie;
 uint32_t mode,percent;uint64_t expected_epoch,expected_registry;
} v6_request;
typedef struct {
 uint64_t native_handle;float cached_points[4],cached_ppp;
 int32_t raw_allocation[4],backing[2];uint32_t raw_gtk_g,play_mode_view;
} v6_view;
typedef struct {
 uint64_t native_handle;float cached_content_points[4];
 int32_t raw_client[4],raw_fixed[4];uint32_t show_mode,reserved;
} v6_window;
/* No delegates retained across a managed domain. Caller submits current IDs on
 * each call. No setter/registration creates a timer or Unity callback. */
V6_VISIBLE int unity_v6_query(uint32_t abi,v6_status *out,uint32_t bytes);
V6_VISIBLE int unity_v6_snapshot(uint32_t abi,v6_window *windows,uint32_t window_cap,
 v6_view *views,uint32_t view_cap,uint32_t *window_count,uint32_t *view_count);
V6_VISIBLE int unity_v6_request(const v6_request *request,uint32_t bytes);
V6_VISIBLE int unity_v6_checkpoint(uint64_t domain_cookie,uint64_t prepared_epoch);
/* One-shot domain-owned rendezvous on the measured priority0 native owner.
 * Queue/cancel only from captured owner TID; callback MUST catch exceptions.
 * Managed caller roots callback/context until completion/cancel and cancels
 * beforeAssemblyReload/quitting. No automatic replay. Not a production lease. */
typedef int (*v6_owner_callback)(uint64_t domain_cookie,uint64_t request_cookie,void *context);
V6_VISIBLE int unity_v6_owner_enqueue(uint64_t domain_cookie,uint64_t request_cookie,v6_owner_callback,void *context);
V6_VISIBLE int unity_v6_owner_cancel(uint64_t domain_cookie);
/* Real native callback completion acknowledgment; additive ABI1 export.
 * completed is set ONLY after reverse-P/Invoke returned to native. cleared means
 * no pending/saved callable delegate/context remains. Query on the next NORMAL
 * managed Update; never release roots from callback finally or by elapsed time.
 * Eight identity-only receipts retained until explicit forget; full rejects new
 * enqueue instead of overwriting evidence. Query/forget on captured owner TID.
 * Release condition: !in_flight && cleared && (completed||cancelled||expired).
 */
typedef struct {
 uint32_t abi,size;uint64_t domain_cookie,request_cookie,sequence;
 uint32_t queued,in_flight,completed,cleared,cancelled,expired;
 int32_t callback_rc;uint32_t reserved;
} v6_owner_completion;
V6_VISIBLE int unity_v6_owner_completion(uint32_t abi,uint64_t domain_cookie,uint64_t request_cookie,v6_owner_completion *out,uint32_t bytes);
V6_VISIBLE int unity_v6_owner_completion_forget(uint64_t domain_cookie,uint64_t request_cookie);


/* Instrumentation integration for audited full envelopes only. They record
 * activity; no readiness gate is inferred from balanced counters alone. */
/* Per-wrapper counters: size32 =31wrappers+factor helper. Out-of-scope is
 * observational nesting absence, distinct from missing ep_begin binding. */
typedef struct {uint32_t abi,size;uint64_t pointer;float ppp,origin[2];int32_t stack_depth,display;uint32_t known;} v6_gui_state;
V6_VISIBLE int unity_v6_gui_query(uint32_t abi,v6_gui_state *out,uint32_t bytes);
/* Verifies actual cached31c matches current mapped liveGUIView rawGDKorigin/U.
 * Nonzero origins are valid. Caller must retain returned measured values. */
V6_VISIBLE int unity_v6_gui_origin_check(uint32_t abi,uint64_t gui,float target_u,float observed_origin[2]);
/* Struct layout is the bundled rendering/boundary/render_boundary.h rb_snapshot. */
V6_VISIBLE int unity_v6_boundary_query(void *out,uint32_t bytes);
V6_VISIBLE int unity_v6_wrapper_coverage(uint64_t calls[32],uint64_t outside_scopes[32],uint32_t cap);
void v6_operation_enter(uint32_t lane,uint64_t native_handle);
void v6_operation_exit(uint32_t lane,uint64_t native_handle);
void v6_mark_wrapper_unbound(void);
void v6_bootstrap(uintptr_t image);
void v6_menu_created(void);
void v6_set_installed(void);
#ifdef __cplusplus
}
#endif
#endif
