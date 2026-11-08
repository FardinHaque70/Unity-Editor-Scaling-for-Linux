#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define CG_ABI 1u
enum {CG_OK=0,CG_ARGUMENT=1,CG_OWNER=2,CG_STALE=3,CG_MODE=4,CG_NOT_READY=5,CG_CHART=6};
enum {CG_FIXED=1,CG_VIEWPORT=2,CG_SCROLLED=3,CG_MENUBAR=4};
typedef struct {int32_t x,y,w,h;} cg_rect;
typedef struct {
 uint64_t native,generation;uint32_t mode,reserved;
 void *top,*fixed,*menubar;float cached_points[4];
} cg_identity;
typedef struct {cg_rect allocation;int32_t mapped,g,kind,reserved;} cg_widget;
typedef struct {
 void*context;
 /* MUST check initialized/non-destroying/startup-ignore readiness, existing
  * owner/context/domain/registry and exact generation
  * BEFORE dereferencing native. Return CG_OK or refusal; no event pumping. */
 int(*resolve)(void*,uint64_t native,uint64_t generation,cg_identity*);
 void*(*parent)(void*,void*widget);
 int(*widget)(void*,void*widget,cg_widget*);
 int(*window)(void*,void*top,cg_rect*); /* GTK window position/size source */
 int(*origin)(void*,void*widget,int32_t xy[2]); /* GDK window origin source */
} cg_host;
typedef struct {
 uint32_t abi,size;uint64_t native,generation;uint32_t mode,reserved;
 cg_rect top_position_size_L,fixed_L,viewport_L,content_L,menu_L;
 int32_t original_screen_origin_L[2];
 float cached_points[4],target_container_points[4],target_root_points[4];
 float target_original_screen_origin_points[2],target_u;
 int32_t menu_height_points;uint32_t fixed_larger_than_visible;
} cg_sample;
/* Read-only per-window callback; output cleared on any refusal. It does NOT
 * widen V6_LAB_ABI, update a receipt, publish U/caches, resize or call managed.
 * Caller must journal/recheck ALL admitted windows in its future bounded lease.
 * Main0/4 only; actualG1 and targetU1/1.5 currently supported. */
int cg_read(const cg_host*,uint64_t native,uint64_t generation,float target_u,cg_sample*);
#ifdef __cplusplus
}
#endif
