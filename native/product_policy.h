#ifndef UNITY_PRODUCT_POLICY_H
#define UNITY_PRODUCT_POLICY_H
#include <stdint.h>
#include <sys/types.h>
#ifdef __cplusplus
extern "C" {
#endif
#define UPS_POLICY_ABI 1u
#define UPS_SETTINGS_MAX_BYTES (1024u * 1024u)
enum ups_mode { UPS_DEFAULT = 0, UPS_CUSTOM = 1, UPS_UNKNOWN = UINT32_MAX };
enum ups_result {
    UPS_OK = 0, UPS_ARGUMENT = -1, UPS_UNSAFE_FILE = -2,
    UPS_IO = -3, UPS_TOO_LARGE = -4, UPS_JSON = -5,
    UPS_SCHEMA = -6, UPS_PROFILE = -7, UPS_MEMORY = -8, UPS_CHANGED = -9,
    UPS_HOST_ENV_SCHEMA = -10, UPS_ENV_WRITE = -11, UPS_ENV_ROLLBACK = -12
};
typedef struct ups_policy {
    uint32_t abi, size, mode, percent;
    float u;
    uint32_t profile_present;
    uint64_t revision;
} ups_policy;
/* One read-only snapshot of the app's atomic settings document. No global
 * cache, environment edits, project lookup, Unity/GTK calls or code execution.
 * settings_path must be absolute, without symlink/dot path components.
 * public_editor must already be the canonical app profile key (realpath exact),
 * not a temporary runtime copy or the preserved original ELF backup path.
 * A missing file/profile is DEFAULT with revision0. An explicit false override
 * is DEFAULT with its saved revision; retained custom scale is still validated.
 * DEFAULT U0/percent0 is a sentinel, never a custom100/desktop value.
 * On ANY refusal output.mode remains UNKNOWN. Caller must inspect the rc and
 * record a refusal; never silently reinterpret a malformed file as DEFAULT.
 * Atomic file replacement may produce the previous or next complete revision.
 */
int ups_read_settings(const char *settings_path, const char *public_editor,
                      uid_t expected_uid, ups_policy *output);
const char *ups_result_text(int result);
#ifdef __cplusplus
}
#endif
#endif
