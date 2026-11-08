#ifndef UNITY_NATIVE_SCOPE_GUARD_H
#define UNITY_NATIVE_SCOPE_GUARD_H
/* Linux/glibc lab helper. No Unity calls, code writes, environment changes,
 * licensing operations, argv rewriting or constructor of its own.
 * GUI_CANDIDATE still requires the existing enable + exact hash/byte guards.
 */
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

enum usg_scope { USG_ERROR = -1, USG_FOREIGN = 0, USG_BYPASS = 1,
                 USG_GUI_CANDIDATE = 2 };
struct usg_result { enum usg_scope scope; const char *reason; };

static inline int usg_ascii_equal(const char *a, const char *b) {
    if (!a || !b) return 0;
    while (*a && *b) {
        unsigned char x = (unsigned char)*a++, y = (unsigned char)*b++;
        if (x >= 'A' && x <= 'Z') x += 'a' - 'A';
        if (y >= 'A' && y <= 'Z') y += 'a' - 'A';
        if (x != y) return 0;
    }
    return !*a && !*b;
}

static inline struct usg_result usg_classify(const char *actual_exe,
        const char *expected_exe, size_t argc, const char *const *argv) {
    static const char *const bypass[] = {
        "-batchmode", "-nographics", "-version", "--version", "-help", "--help",
        "-returnlicense", "-manuallicensefile", "-createmanualactivationfile"
    };
    if (!actual_exe || !expected_exe || expected_exe[0] != '/')
        return (struct usg_result){USG_ERROR, "invalid executable identity"};
    if (strcmp(actual_exe, expected_exe))
        return (struct usg_result){USG_FOREIGN, "different executable"};
    if (!argc || !argv || !argv[0])
        return (struct usg_result){USG_ERROR, "unavailable process arguments"};
    for (size_t i = 1; i < argc; ++i) {
        if (!argv[i])
            return (struct usg_result){USG_ERROR, "malformed process arguments"};
        for (size_t j = 0; j < sizeof bypass / sizeof *bypass; ++j)
            if (usg_ascii_equal(argv[i], bypass[j]))
                return (struct usg_result){USG_BYPASS, bypass[j]};
        /* Verified installed IsLightBakerWorkerProcess checks first -name
         * value with case-sensitive BeginsWith("LightBakerWorker"). Asset
         * import workers already have unconditional -batchMode in this ELF.
         */
        if (usg_ascii_equal(argv[i], "-name") && i + 1 < argc && argv[i+1] &&
            !strncmp(argv[i+1], "LightBakerWorker", 16))
            return (struct usg_result){USG_BYPASS, "LightBakerWorker role"};
    }
    return (struct usg_result){USG_GUI_CANDIDATE, "GUI candidate; verify build"};
}

/* Read before hash/log/dlsym/mprotect. Unreadable or oversized own command
 * line is an error, never permission to patch. Foreign helpers need no argv.
 */
static inline struct usg_result usg_current_scope(const char *expected_exe) {
    char exe[PATH_MAX];
    ssize_t len = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (len < 0 || (size_t)len >= sizeof exe - 1)
        return (struct usg_result){USG_ERROR, "cannot read executable identity"};
    exe[len] = 0;
    if (!expected_exe || expected_exe[0] != '/')
        return (struct usg_result){USG_ERROR, "invalid expected executable"};
    if (strcmp(exe, expected_exe))
        return (struct usg_result){USG_FOREIGN, "different executable"};
    const size_t limit = 4u * 1024u * 1024u;
    size_t size = 0, capacity = 4096;
    char *data = malloc(capacity);
    int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
    if (!data || fd < 0) {
        free(data); if (fd >= 0) close(fd);
        return (struct usg_result){USG_ERROR, "cannot read process arguments"};
    }
    struct usg_result result = {USG_ERROR, "invalid or oversized command line"};
    for (;;) {
        if (size == capacity) {
            if (capacity == limit) goto done;
            size_t next = capacity * 2;
            char *grown = realloc(data, next);
            if (!grown) goto done;
            data = grown; capacity = next;
        }
        ssize_t n = read(fd, data + size, capacity - size);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) goto done;
        if (!n) break;
        size += (size_t)n;
    }
    if (!size || data[size-1]) goto done;
    size_t argc = 0;
    for (size_t i = 0; i < size; ++i) if (!data[i]) ++argc;
    const char **argv = malloc(argc * sizeof *argv);
    if (!argv) goto done;
    size_t index = 0;
    argv[index++] = data;
    for (size_t i = 0; i + 1 < size; ++i)
        if (!data[i]) argv[index++] = data + i + 1;
    result = usg_classify(exe, expected_exe, argc, argv);
    free(argv);
done:
    close(fd); free(data); return result;
}

static inline int usg_self_starttime(unsigned long long *out) {
    char text[4096];
    int fd = open("/proc/self/stat", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n;
    do { n = read(fd, text, sizeof text - 1); } while (n < 0 && errno == EINTR);
    close(fd);
    if (n <= 0 || (size_t)n >= sizeof text - 1) { errno = EINVAL; return -1; }
    text[n] = 0;
    char *p = strrchr(text, ')');
    if (!p || p[1] != ' ') { errno = EINVAL; return -1; }
    p += 2;
    for (int field = 3; field < 22; ++field) {
        p = strchr(p, ' ');
        if (!p || !*++p) { errno = EINVAL; return -1; }
    }
    if (*p < '0' || *p > '9') { errno = EINVAL; return -1; }
    errno = 0; char *end;
    unsigned long long value = strtoull(p, &end, 10);
    if (errno || (*end && *end != ' ')) { errno = EINVAL; return -1; }
    *out = value; return 0;
}

/* Caller validates base is inside its owned run directory. Only call after
 * GUI scope and existing enable/hash/byte guards. Never open the inherited
 * unsuffixed base. Exclusive process-owned logs preserve fail-closed behavior.
 * A fresh GUI replacement may inherit base yet has a different identity.
 */
static inline int usg_open_gui_log(const char *base, char *path, size_t capacity) {
    unsigned long long start;
    if (!base || base[0] != '/' || !path || !capacity) { errno = EINVAL; return -1; }
    if (usg_self_starttime(&start)) return -1;
    int n = snprintf(path, capacity, "%s.gui-%ld-%llu", base, (long)getpid(), start);
    if (n < 0 || (size_t)n >= capacity) { errno = ENAMETOOLONG; return -1; }
    return open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
}
#endif
