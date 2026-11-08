#pragma once
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
int nsp_strip_own_preload(const char *mapped_library);
int nsp_has_foreign_preload(const char *mapped_library);
int nsp_open_receipt(const char *prefix,char *actual,size_t capacity);
int nsp_custom_session(void); /*0supported,-1session,-2renderer argv,-3read*/
#ifdef __cplusplus
}
#endif
