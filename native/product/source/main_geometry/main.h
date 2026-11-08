#pragma once
#include "geometry/geometry.h"
#include "content_geometry/accepted_content.h"
#include "v6_epoch_bridge.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct{vg_patch patches[3];size_t count;} mp_plan;
/* No target writes: fresh-launch exact bytes/context checked before any RB
 * writes. Source-linked clone only; does not replace a render-boundary entry. */
int mp_prepare(uintptr_t image,mp_plan*);
int mp_mark_installed(void);
int mp_validate_target(const cg_sample*,float from_u);
void mp_adjust_request(void*top,uintptr_t source,const ep_snapshot*,int*width_L,int*height_L);
vg_rect mp_menu_rect(void*,const int*slots);
void mp_configure_rect(void*,float*wh,int allocated_y_points,float*xy);
void mp_allocated_tail(void*allocation,void*container);
/* Captain supplies current owner/context/registry/birth/readiness guarded
 * read-only helpers. No object retained across callbacks, no event pump. */
uint64_t v6_main_handle(void);
int v6_main_read(uint64_t native,float target_u,cg_sample*);
int v6_main_menu_height(uint64_t native,int*height_L);
void v6_main_trace(unsigned source,const cg_sample*,unsigned depth);
#ifdef __cplusplus
}
#endif
