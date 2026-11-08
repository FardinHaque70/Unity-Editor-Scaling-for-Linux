#ifndef UNITY_PRODUCT_HOST_ENVIRONMENT_H
#define UNITY_PRODUCT_HOST_ENVIRONMENT_H
#include "product_policy.h"
#ifdef __cplusplus
extern "C" {
#endif
#define UPS_HOST_ENV_KEY "UNITY_EDITOR_SCALING_HOST_ENV"
#define UPS_HOST_ENV_ABI 1u
#define UPS_HOST_ENV_MAX_BYTES 4096u
#define UPS_HOST_ENV_VALUE_MAX_BYTES 512u
/* Strict JSON envelope:
 * {"abi":1,"GDK_SCALE":string|null,"GDK_DPI_SCALE":string|null,
 *  "GDK_BACKEND":string|null}
 * Exact keys/types, unique decoded keys, finite UTF-8, no embedded NUL.
 * Validate the WHOLE envelope and capture current values before any mutation.
 * null unsets; an empty string remains present and empty. Does not alter the
 * envelope itself, settings/public-key metadata, LD_PRELOAD or any other key.
 * Invoke on the pristine constructor thread BEFORE GTK initialization and
 * BEFORE Default/refusal/helper role paths. Missing/malformed data refuses
 * without guessing original host values or making any environment change.
 * On write failure attempts rollback; UPS_ENV_ROLLBACK means rollback also
 * failed and caller must not claim a neutral host or install scaling hooks.
 */
int ups_restore_host_env_json(const char *raw);
#ifdef __cplusplus
}
#endif
#endif
