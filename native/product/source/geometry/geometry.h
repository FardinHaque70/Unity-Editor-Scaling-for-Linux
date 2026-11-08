#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct{float x,y,w,h;} vg_rect;
typedef struct {
 int(*gtk_scale)(void*);
 void(*resize)(void*,int,int);void(*move)(void*,int,int);
 void(*fixed_move)(void*,void*,int,int);void(*size_request)(void*,int,int);
} vg_host;
typedef struct {const char*name;uintptr_t va;size_t len;unsigned char before[64],after[64];} vg_patch;
/* LINK ONLY into the already-guarded V6 DSO. No constructor/loader/installer.
 * Bind real GTK APIs before callback admission, in fresh launch initialization.
 * Host verifies full supported ELF + all guards BEFORE installing any payload.
 * Never dlopen/stack this as another native scaling backend. */
int vg_bind(const vg_host*);
size_t vg_patches(vg_patch out[4]);
/* Entry helpers referenced by returned payloads; each consumes exactly ONE
 * v6_conversion_snapshot. Scope/epoch/owner admission belongs to existing V6. */
void vg_container_request(void*,const vg_rect*,uintptr_t original_rect_source);
void vg_child_request(void*,void*,const vg_rect*);
int vg_accepted_changed(void*container,const vg_rect*accepted,unsigned equality_mask);
#ifdef __cplusplus
}
#endif
