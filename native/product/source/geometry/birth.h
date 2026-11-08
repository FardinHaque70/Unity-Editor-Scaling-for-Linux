#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum{V6_BIRTH_VIEW=1,V6_BIRTH_WINDOW=2};
uint64_t v6_birth_begin(void *native,unsigned kind);
void v6_birth_ready(void *native,unsigned kind,uint64_t token);
void v6_birth_destroy(void *native,unsigned kind);
uint64_t v6_birth_lookup(uint64_t native,unsigned kind);
uint64_t v6_birth_generation(void);
int v6_birth_poisoned(void);
#ifdef __cplusplus
}
#endif
