#define _GNU_SOURCE
#include "product_policy.h"
#include "host_environment.h"
#include <errno.h>
#include <fcntl.h>
#include <json-c/json.h>
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Walk with directory FDs: O_NOFOLLOW only on the final file would permit a
 * replaced/symlinked parent. O_NONBLOCK prevents a FIFO from hanging startup
 * before fstat rejects it. Nothing creates or modifies a file/directory. */
static int canonical_spelling(const char *path)
{
    if (!path || path[0] != '/' || !path[1] || strnlen(path, PATH_MAX) >= PATH_MAX) return 0;
    const char *part = path + 1;
    for (const char *p = part;; ++p) if (*p == '/' || !*p) {
        size_t length = (size_t)(p - part);
        if (!length || (length == 1 && part[0] == '.') ||
            (length == 2 && part[0] == '.' && part[1] == '.')) return 0;
        if (!*p) break;
        part = p + 1;
    }
    return 1;
}
static int open_settings(const char *path, int *descriptor)
{
    if (!canonical_spelling(path)) return UPS_ARGUMENT;
    char *parts = strdup(path + 1);
    if (!parts) return UPS_MEMORY;
    int directory = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (directory < 0) { free(parts); return UPS_IO; }
    int result = UPS_OK;
    char *cursor = parts, *part;
    while ((part = strsep(&cursor, "/")) != NULL) {
        if (!*part || !strcmp(part, ".") || !strcmp(part, "..")) { result = UPS_ARGUMENT; break; }
        int last = cursor == NULL;
        int fd = openat(directory, part, O_RDONLY | O_CLOEXEC | O_NOFOLLOW |
                        (last ? O_NONBLOCK : O_DIRECTORY));
        if (fd < 0) {
            result = errno == ENOENT ? 1 : (errno == ELOOP || errno == ENOTDIR ? UPS_UNSAFE_FILE : UPS_IO);
            break;
        }
        if (last) { *descriptor = fd; break; }
        close(directory); directory = fd;
    }
    close(directory); free(parts); return result;
}
static int integer(struct json_object *value, int64_t minimum, int64_t maximum)
{
    return value && json_object_get_type(value) == json_type_int &&
           json_object_get_int64(value) >= minimum && json_object_get_int64(value) <= maximum;
}
static int field(struct json_object *object, const char *key, struct json_object **value)
{ return json_object_object_get_ex(object, key, value); }

/* JSON-c intentionally accepts duplicate keys with last-value semantics. App
 * policy must not depend on an ambiguous duplicate. The main strict parser has
 * already validated syntax; this bounded pass checks decoded object key identity
 * (including escaped spellings) without implementing a second value decoder. */
static void whitespace(const char **p, const char *end)
{ while (*p < end && (**p == ' ' || **p == '\t' || **p == '\r' || **p == '\n')) ++*p; }
static const char *string_end(const char *p, const char *end)
{
    for (++p; p < end; ++p) {
        if (*p == '\\') { if (++p == end) return NULL; }
        else if (*p == '"') return p + 1;
    }
    return NULL;
}
static int unique_keys(const char **p, const char *end, unsigned depth)
{
    if (depth > 32) return UPS_JSON;
    whitespace(p, end); if (*p == end) return UPS_JSON;
    if (**p == '"') { const char *next = string_end(*p, end); if (!next) return UPS_JSON; *p = next; return UPS_OK; }
    if (**p != '{' && **p != '[') {
        while (*p < end && !strchr(" \t\r\n,]}", **p)) ++*p;
        return UPS_OK;
    }
    int object = **p == '{'; char finish = object ? '}' : ']'; ++*p;
    struct json_object *seen = object ? json_object_new_object() : NULL;
    if (object && !seen) return UPS_MEMORY;
    int result = UPS_OK;
    whitespace(p, end);
    while (*p < end && **p != finish) {
        if (object) {
            const char *start = *p, *next = **p == '"' ? string_end(*p, end) : NULL;
            if (!next) { result = UPS_JSON; break; }
            struct json_tokener *token = json_tokener_new_ex(4);
            if (!token) { result = UPS_MEMORY; break; }
            struct json_object *key = json_tokener_parse_ex(token, start, (int)(next - start));
            int valid = key && json_object_get_type(key) == json_type_string &&
                        json_tokener_get_error(token) == json_tokener_success;
            json_tokener_free(token);
            const char *name = valid ? json_object_get_string(key) : NULL;
            struct json_object *unused;
            if (!valid || (size_t)json_object_get_string_len(key) != strlen(name) ||
                json_object_object_get_ex(seen, name, &unused)) result = UPS_JSON;
            else {
                struct json_object *present = json_object_new_boolean(1);
                if (!present) result = UPS_MEMORY;
                else if (json_object_object_add(seen, name, present)) { json_object_put(present); result = UPS_MEMORY; }
            }
            if (key) json_object_put(key);
            if (result) break;
            *p = next; whitespace(p, end);
            if (*p == end || *(*p)++ != ':') { result = UPS_JSON; break; }
        }
        result = unique_keys(p, end, depth + 1); if (result) break;
        whitespace(p, end);
        if (*p < end && **p == ',') { ++*p; whitespace(p, end); }
        else break;
    }
    if (!result && (*p == end || *(*p)++ != finish)) result = UPS_JSON;
    if (seen) json_object_put(seen);
    return result;
}
static int finite_json(struct json_object *value)
{
    if (!value) return 1; /* JSON null is allowed for unrelated future fields. */
    enum json_type type = json_object_get_type(value);
    if (type == json_type_double) return isfinite(json_object_get_double(value));
    if (type == json_type_array) {
        size_t n = json_object_array_length(value);
        for (size_t i = 0; i < n; ++i) if (!finite_json(json_object_array_get_idx(value, i))) return 0;
    } else if (type == json_type_object) {
        struct json_object_iter iter;
        json_object_object_foreachC(value, iter) if (!finite_json(iter.val)) return 0;
    }
    return 1;
}
int ups_strict_document(const char *data, size_t length, struct json_object **out)
{
    *out = NULL;
    if (!data || !length || length > 65536) return UPS_JSON;
    struct json_tokener *token = json_tokener_new_ex(32);
    if (!token) return UPS_MEMORY;
    json_tokener_set_flags(token, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
    struct json_object *doc = json_tokener_parse_ex(token, data, (int)length);
    int rc = UPS_JSON;
    if (json_tokener_get_error(token) == json_tokener_success && doc &&
        json_tokener_get_parse_end(token) == length && finite_json(doc)) {
        const char *cursor = data;
        rc = unique_keys(&cursor, data + length, 0);
        whitespace(&cursor, data + length);
        if (cursor != data + length) rc = UPS_JSON;
    }
    json_tokener_free(token);
    if (rc) { if (doc) json_object_put(doc); return rc; }
    *out = doc; return UPS_OK;
}
static int profile(struct json_object *value, uint32_t *mode, uint32_t *percent, uint64_t *revision)
{
    struct json_object *enabled, *scale, *rev, *optional;
    if (!value || json_object_get_type(value) != json_type_object ||
        !field(value, "override_enabled", &enabled) || json_object_get_type(enabled) != json_type_boolean ||
        !field(value, "ui_scale_percent", &scale) || !integer(scale, 100, 200) ||
        !field(value, "control_revision", &rev) || !integer(rev, 1, INT64_C(9007199254740991))) return UPS_PROFILE;
    if (field(value, "follow_desktop", &optional) &&
        (json_object_get_type(optional) != json_type_boolean || json_object_get_boolean(optional))) return UPS_PROFILE;
    if (field(value, "render_scale", &optional) && !integer(optional, 1, 4)) return UPS_PROFILE;
    *mode = json_object_get_boolean(enabled) ? UPS_CUSTOM : UPS_DEFAULT;
    *percent = *mode == UPS_CUSTOM ? (uint32_t)json_object_get_int(scale) : 0;
    *revision = (uint64_t)json_object_get_int64(rev);
    return UPS_OK;
}
static int parse(const char *data, size_t length, const char *editor, ups_policy *out)
{
    struct json_tokener *token = json_tokener_new_ex(32);
    if (!token) return UPS_MEMORY;
    json_tokener_set_flags(token, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
    struct json_object *document = json_tokener_parse_ex(token, data, (int)length);
    int result = UPS_JSON;
    if (json_tokener_get_error(token) != json_tokener_success || !document ||
        json_tokener_get_parse_end(token) != length || !finite_json(document)) goto done;
    const char *cursor = data;
    result = unique_keys(&cursor, data + length, 0);
    if (result) goto done;
    whitespace(&cursor, data + length);
    if (cursor != data + length) { result = UPS_JSON; goto done; }
    struct json_object *schema, *editors, *extra;
    if (json_object_get_type(document) != json_type_object ||
        !field(document, "schema_version", &schema) || !integer(schema, 2, 2) ||
        !field(document, "editors", &editors) || json_object_get_type(editors) != json_type_object) { result = UPS_SCHEMA; goto done; }
    if (field(document, "extra_editors", &extra)) {
        if (json_object_get_type(extra) != json_type_array) { result = UPS_SCHEMA; goto done; }
        for (size_t i = 0; i < json_object_array_length(extra); ++i)
            if (json_object_get_type(json_object_array_get_idx(extra, i)) != json_type_string) { result = UPS_SCHEMA; goto done; }
    }
    ups_policy choice = {UPS_POLICY_ABI, sizeof choice, UPS_DEFAULT, 0, 0, 0, 0};
    struct json_object_iter iter;
    json_object_object_foreachC(editors, iter) {
        uint32_t mode, percent; uint64_t revision;
        if (!canonical_spelling(iter.key) || (result = profile(iter.val, &mode, &percent, &revision)) != UPS_OK) {
            result = UPS_PROFILE; goto done;
        }
        if (!strcmp(iter.key, editor)) {
            choice.mode = mode; choice.percent = percent; choice.revision = revision;
            choice.u = mode == UPS_CUSTOM ? (float)(percent / 100.0) : 0.0f;
            choice.profile_present = 1;
        }
    }
    *out = choice; result = UPS_OK;
done:
    if (document) json_object_put(document);
    json_tokener_free(token);
    return result;
}
int ups_read_settings(const char *path, const char *editor, uid_t uid, ups_policy *out)
{
    if (!out) return UPS_ARGUMENT;
    memset(out, 0, sizeof *out); out->abi = UPS_POLICY_ABI; out->size = sizeof *out; out->mode = UPS_UNKNOWN;
    if (!editor || editor[0] != '/' || strnlen(editor, PATH_MAX) >= PATH_MAX) return UPS_ARGUMENT;
    char *canonical = realpath(editor, NULL);
    if (!canonical) return UPS_ARGUMENT;
    int same = !strcmp(canonical, editor); free(canonical);
    if (!same) return UPS_ARGUMENT;
    int fd = -1, result = open_settings(path, &fd);
    if (result == 1) { out->mode = UPS_DEFAULT; return UPS_OK; }
    if (result) return result;
    struct stat before, after;
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_uid != uid) { close(fd); return UPS_UNSAFE_FILE; }
    if (before.st_size <= 0) { close(fd); return UPS_JSON; }
    if ((uint64_t)before.st_size > UPS_SETTINGS_MAX_BYTES) { close(fd); return UPS_TOO_LARGE; }
    size_t length = (size_t)before.st_size;
    char *data = malloc(length + 1);
    if (!data) { close(fd); return UPS_MEMORY; }
    size_t have = 0;
    while (have < length) {
        ssize_t got = pread(fd, data + have, length - have, (off_t)have);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) { result = got < 0 ? UPS_IO : UPS_CHANGED; goto done; }
        have += (size_t)got;
    }
    if (fstat(fd, &after)) { result = UPS_IO; goto done; }
    if (before.st_size != after.st_size || before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
        before.st_mtim.tv_nsec != after.st_mtim.tv_nsec || after.st_uid != uid) { result = UPS_CHANGED; goto done; }
    data[length] = 0;
    result = parse(data, length, editor, out);
done:
    free(data); close(fd); return result;
}
int ups_restore_host_env_json(const char *raw)
{
    if (!raw) return UPS_ARGUMENT;
    size_t length = strnlen(raw, UPS_HOST_ENV_MAX_BYTES + 1u);
    if (!length || length > UPS_HOST_ENV_MAX_BYTES) return UPS_HOST_ENV_SCHEMA;
    struct json_tokener *token = json_tokener_new_ex(8);
    if (!token) return UPS_MEMORY;
    json_tokener_set_flags(token, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
    struct json_object *document = json_tokener_parse_ex(token, raw, (int)length);
    int result = UPS_JSON;
    char *before[3] = {NULL, NULL, NULL};
    const char *after[3] = {NULL, NULL, NULL};
    static const char *const names[3] = {"GDK_SCALE", "GDK_DPI_SCALE", "GDK_BACKEND"};
    if (json_tokener_get_error(token) != json_tokener_success || !document ||
        json_tokener_get_parse_end(token) != length || !finite_json(document)) goto done;
    const char *cursor = raw;
    result = unique_keys(&cursor, raw + length, 0);
    if (result) goto done;
    whitespace(&cursor, raw + length);
    struct json_object *abi;
    if (cursor != raw + length || json_object_get_type(document) != json_type_object ||
        json_object_object_length(document) != 4 || !field(document, "abi", &abi) || !integer(abi, 1, 1)) {
        result = UPS_HOST_ENV_SCHEMA; goto done;
    }
    for (unsigned i = 0; i < 3; ++i) {
        struct json_object *value;
        if (!field(document, names[i], &value)) { result = UPS_HOST_ENV_SCHEMA; goto done; }
        if (value) {
            if (json_object_get_type(value) != json_type_string) { result = UPS_HOST_ENV_SCHEMA; goto done; }
            size_t size = (size_t)json_object_get_string_len(value);
            const char *text = json_object_get_string(value);
            if (size > UPS_HOST_ENV_VALUE_MAX_BYTES || size != strlen(text)) { result = UPS_HOST_ENV_SCHEMA; goto done; }
            after[i] = text;
        }
    }
    // No setenv/unsetenv before every field above has passed validation.
    for (unsigned i = 0; i < 3; ++i) {
        const char *current = getenv(names[i]);
        if (current && !(before[i] = strdup(current))) { result = UPS_MEMORY; goto done; }
    }
    result = UPS_OK;
    for (unsigned i = 0; i < 3; ++i) {
        int failed = after[i] ? setenv(names[i], after[i], 1) : unsetenv(names[i]);
        if (!failed) continue;
        result = UPS_ENV_WRITE;
        for (unsigned j = 0; j <= i; ++j)
            if (before[j] ? setenv(names[j], before[j], 1) : unsetenv(names[j])) result = UPS_ENV_ROLLBACK;
        break;
    }
done:
    for (unsigned i = 0; i < 3; ++i) free(before[i]);
    if (document) json_object_put(document);
    json_tokener_free(token);
    return result;
}
const char *ups_result_text(int result)
{
    switch (result) {
    case UPS_OK: return "policy read";
    case UPS_ARGUMENT: return "absolute settings path and canonical public Editor key required";
    case UPS_UNSAFE_FILE: return "settings must be a regular file owned by this user with no symlink components";
    case UPS_IO: return "settings could not be read";
    case UPS_TOO_LARGE: return "settings exceed 1 MiB";
    case UPS_JSON: return "settings are not strict finite unambiguous UTF-8 JSON";
    case UPS_SCHEMA: return "settings require schema 2 and an Editor map";
    case UPS_PROFILE: return "profile needs an explicit boolean override, integer100..200 scale and valid revision";
    case UPS_MEMORY: return "policy reader allocation failed";
    case UPS_CHANGED: return "settings changed during the read";
    case UPS_HOST_ENV_SCHEMA: return "host environment requires exact ABI1 keys and string-or-null GDK values";
    case UPS_ENV_WRITE: return "host environment restoration failed; original values rolled back";
    case UPS_ENV_ROLLBACK: return "host environment restoration and rollback failed";
    default: return "unknown policy reader refusal";
    }
}
