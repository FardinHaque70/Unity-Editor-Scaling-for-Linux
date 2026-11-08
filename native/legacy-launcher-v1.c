#define _GNU_SOURCE
/* Ordinary ELF exec launcher: no GTK, window, renderer or input operations. */
#include "config.h"
#include "product_policy.h"
#include <errno.h>
#include <fcntl.h>
#include <json-c/json.h>
#include <openssl/evp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static const char managed_marker[] __attribute__((used))="UNITY_EDITOR_SCALING_NATIVE_LAUNCHER_V1";
extern char **environ;
extern int ups_restore_host_env_json(const char *raw);
static void refuse(const char *reason) { fprintf(stderr,"Unity Editor Scaling: %s; launcher left the Editor unstarted.\n",reason); exit(126); }
static int hash(const char *path,const char *expected) {
 int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW); struct stat a,b;
 if(fd<0||fstat(fd,&a)||!S_ISREG(a.st_mode)){if(fd>=0)close(fd);return 0;}
 EVP_MD_CTX *context=EVP_MD_CTX_new(); if(!context){close(fd);return 0;}
 int ok=EVP_DigestInit_ex(context,EVP_sha256(),NULL);unsigned char block[65536],out[32]={0};ssize_t n;
 while(ok&&(n=read(fd,block,sizeof block))!=0){if(n<0){if(errno==EINTR)continue;ok=0;break;}ok=EVP_DigestUpdate(context,block,(size_t)n);}
 unsigned count=0;if(ok)ok=EVP_DigestFinal_ex(context,out,&count);
 EVP_MD_CTX_free(context);if(fstat(fd,&b)||a.st_dev!=b.st_dev||a.st_ino!=b.st_ino||a.st_size!=b.st_size||
   a.st_mtim.tv_sec!=b.st_mtim.tv_sec||a.st_mtim.tv_nsec!=b.st_mtim.tv_nsec||a.st_ctim.tv_sec!=b.st_ctim.tv_sec||a.st_ctim.tv_nsec!=b.st_ctim.tv_nsec)ok=0;
 close(fd);char hex[65];for(unsigned i=0;i<32;i++)snprintf(hex+i*2,3,"%02x",out[i]);return ok&&count==32&&!strcmp(hex,expected);
}
static int same_library(const char *path) {struct stat a,b;return !strcmp(path,NATIVE_LIBRARY)||(strchr(path,'/')&&!stat(path,&a)&&!stat(NATIVE_LIBRARY,&b)&&a.st_dev==b.st_dev&&a.st_ino==b.st_ino);}
static void strip_own(void) {
 const char *raw=getenv("LD_PRELOAD");if(!raw||!*raw)return;
 char *input=strdup(raw),*output=calloc(strlen(raw)+1,1);if(!input||!output)refuse("loader environment allocation failed");
 char *save=NULL;for(char *part=strtok_r(input,": \t\r\n",&save);part;part=strtok_r(NULL,": \t\r\n",&save))if(!same_library(part)){if(*output)strcat(output,":");strcat(output,part);}
 if(*output){if(setenv("LD_PRELOAD",output,1))refuse("loader environment update failed");}else if(unsetenv("LD_PRELOAD"))refuse("loader environment update failed");
 free(output);free(input);
}
static int bypass(int argc,char **argv) {
 const char *flags[]={"-batchmode","-nographics","-version","--version","-help","--help","-returnlicense","-manuallicensefile","-createmanualactivationfile"};
 for(int i=1;i<argc;i++){
  for(unsigned j=0;j<sizeof flags/sizeof *flags;j++)if(!strcasecmp(argv[i],flags[j]))return 1;
  if(!strcasecmp(argv[i],"-name")&&i+1<argc&&!strncmp(argv[i+1],"LightBakerWorker",16))return 1;
 }
 return 0;
}
int main(int argc,char **argv) {
 const char *envelope=getenv("UNITY_EDITOR_SCALING_HOST_ENV");
 if(envelope&&ups_restore_host_env_json(envelope))refuse("invalid original host environment");
 strip_own();
 struct stat original;
 if(lstat(ORIGINAL_EDITOR,&original)||!S_ISREG(original.st_mode)||access(ORIGINAL_EDITOR,X_OK))refuse("original Editor is missing or unsafe");
 /* Workers bypass native/large hashes, matching the immutable original identity
  * captured at prepare. Normal GUI launch additionally hashes original bytes.
  * A hard-link backup changes ctime, so that field is deliberately not cached. */
 if((unsigned long long)original.st_dev!=ORIGINAL_DEV||(unsigned long long)original.st_ino!=ORIGINAL_INO||
    (unsigned long long)original.st_size!=ORIGINAL_SIZE||original.st_mtim.tv_sec!=ORIGINAL_MTIME_SEC||original.st_mtim.tv_nsec!=ORIGINAL_MTIME_NSEC)
  refuse("original Editor changed since preparation");
 if(bypass(argc,argv)){execve(ORIGINAL_EDITOR,argv,environ);refuse("cannot execute original Editor");}
 if(!hash(ORIGINAL_EDITOR,ORIGINAL_SHA256)||!hash(NATIVE_LIBRARY,NATIVE_SHA256))refuse("Editor/native identity verification failed");
 if(!envelope){
  struct json_object *root=json_object_new_object();if(!root)refuse("host envelope allocation failed");
  json_object_object_add(root,"abi",json_object_new_int(1));
  const char *keys[]={"GDK_SCALE","GDK_DPI_SCALE","GDK_BACKEND"};
  for(unsigned i=0;i<3;i++){const char *value=getenv(keys[i]);if(value&&strlen(value)>512)refuse("original host variable exceeds ABI1 bound");json_object_object_add(root,keys[i],value?json_object_new_string(value):NULL);}
  const char *raw=json_object_to_json_string_ext(root,JSON_C_TO_STRING_PLAIN);
  if(!raw||strlen(raw)>4096||setenv("UNITY_EDITOR_SCALING_HOST_ENV",raw,1))refuse("cannot record original host environment");
  json_object_put(root);
 }
 if(setenv("UNITY_EDITOR_SCALING_SETTINGS",SETTINGS_PATH,1)||setenv("UNITY_EDITOR_SCALING_PUBLIC_EDITOR",PUBLIC_EDITOR,1))refuse("cannot set profile identity");
 /* No factor/mode is sent: one constructor settings read is authoritative. */
 unsetenv("UNITY_NATIVE_STARTUP_MODE");unsetenv("UNITY_NATIVE_STARTUP_PERCENT");unsetenv("UNITY_NATIVE_STARTUP_ENABLE");
 const char *foreign=getenv("LD_PRELOAD");size_t length=strlen(NATIVE_LIBRARY)+(foreign?strlen(foreign):0)+2;
 char *preload=malloc(length);if(!preload)refuse("loader environment allocation failed");
 snprintf(preload,length,"%s%s%s",NATIVE_LIBRARY,foreign&&*foreign?":":"",foreign?foreign:"");
 if(setenv("LD_PRELOAD",preload,1))refuse("cannot set native loader");free(preload);
 execve(ORIGINAL_EDITOR,argv,environ);refuse("cannot execute original Editor");
}
