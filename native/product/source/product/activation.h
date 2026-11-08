#ifndef UNITY_SCALING_ACTIVATION_H
#define UNITY_SCALING_ACTIVATION_H
#include <limits.h>
#include <sys/stat.h>
#ifdef __cplusplus
extern "C" {
#endif
#define NSA_ORIGINAL_SHA "d5e670eab13daa0962126f61354041a1077757a7d2ecb3f3eaff5ac859cbbbec"
typedef struct nsa_config {
 char package[PATH_MAX],public_editor[PATH_MAX],target_exe[PATH_MAX],settings[PATH_MAX];
 char library[PATH_MAX],wrapper[PATH_MAX],library_sha256[65],wrapper_sha256[65];
 unsigned long long dev,ino,size,mtime_ns;
} nsa_config;
/* Derive only; permits helper/foreign bypass before descriptor/hash admission. */
int nsa_paths(const char *own_path,int launcher,nsa_config *out);
/* All paths, descriptor, owner, original identity and all three hashes. */
int nsa_validate(nsa_config *out);
int nsa_hash(const char *path,const char *sha);
const nsa_config *nsa_current(void);
void nsa_use(const nsa_config *config);
#ifdef __cplusplus
}
#endif
#endif
