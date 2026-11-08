#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void nsp_repaint_bind(uintptr_t image);
void nsp_repaint_detach(void *view);
void nsp_repaint_attach(void *view,uint64_t expected_birth);
#ifdef __cplusplus
}
#endif
