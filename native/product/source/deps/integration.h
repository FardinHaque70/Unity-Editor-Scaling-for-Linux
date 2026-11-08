#pragma once
#include "epoch.h"
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Root-only ABI. No functions below install or mutate target instructions. */
struct ep_candidate {const char *name;uintptr_t va;void *replacement;void **original;};
struct ep_gpu_candidate {uintptr_t va;size_t n;void *replacement;};
size_t ep_wrapper_count(void);
const struct ep_candidate *ep_wrapper_candidates(void);
const struct ep_gpu_candidate *ep_gpu_candidates(void); /* four entries */
int ep_wrapper_bind_gtk(uintptr_t image);
int ep_make_originals(uintptr_t image);
int ep_make_gpu_originals(uintptr_t image);
/* Compile-only companion object APIs; caller links GTK3 for geometry. */
int ep_geometry_attach(uintptr_t image,long proven_factory_tid);
int ep_geometry_capture(void);
int ep_geometry_verify(void);
int ep_geometry_release(void);
void ep_paint_enter_observation(void);
void ep_paint_exit_observation(void);
#ifdef __cplusplus
/* PumpGtkMainloop ABI is C++ bool on exact x86_64 build. */
void ep_poll_configure(uintptr_t,bool (*retained_pump)(bool),
                      void (*observe)(uintptr_t,long,unsigned,bool,bool));
bool ep_pump_candidate(bool);
}
#endif
