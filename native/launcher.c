#define _GNU_SOURCE
/* Ordinary ELF exec launcher: no GTK, window, renderer or input operations. */
#include "product/source/product/activation.h"
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
static const char managed_marker[] __attribute__((used))="UNITY_EDITOR_SCALING_NATIVE_LAUNCHER_V2";
extern char **environ;
extern int ups_restore_host_env_json(const char *raw);
static void refuse(const char *reason) { fprintf(stderr,"Unity Editor Scaling: %s; launcher left the Editor unstarted.\n",reason); exit(126); }
static nsa_config activation;
static int same_library(const char *path) {struct stat a,b;return !strcmp(path,activation.library)||(strchr(path,'/')&&!stat(path,&a)&&!stat(activation.library,&b)&&a.st_dev==b.st_dev&&a.st_ino==b.st_ino);}
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
 char own[PATH_MAX];ssize_t n=readlink("/proc/self/exe",own,sizeof own-1);
 if(n<0||(size_t)n>=sizeof own-1)refuse("cannot identify public launcher");own[n]=0;
 if(nsa_paths(own,1,&activation))refuse("cannot derive activation package");
 strip_own();
 if(nsa_validate(&activation))refuse("activation identity verification failed");
 if(bypass(argc,argv)){execve(activation.target_exe,argv,environ);refuse("cannot execute original Editor");}
 if(!envelope){
  struct json_object *root=json_object_new_object();if(!root)refuse("host envelope allocation failed");
  json_object_object_add(root,"abi",json_object_new_int(1));
  const char *keys[]={"GDK_SCALE","GDK_DPI_SCALE","GDK_BACKEND"};
  for(unsigned i=0;i<3;i++){const char *value=getenv(keys[i]);if(value&&strlen(value)>512)refuse("original host variable exceeds ABI1 bound");json_object_object_add(root,keys[i],value?json_object_new_string(value):NULL);}
  const char *raw=json_object_to_json_string_ext(root,JSON_C_TO_STRING_PLAIN);
  if(!raw||strlen(raw)>4096||setenv("UNITY_EDITOR_SCALING_HOST_ENV",raw,1))refuse("cannot record original host environment");
  json_object_put(root);
 }
 if(setenv("UNITY_EDITOR_SCALING_SETTINGS",activation.settings,1)||setenv("UNITY_EDITOR_SCALING_PUBLIC_EDITOR",activation.public_editor,1))refuse("cannot set profile identity");
 /* No factor/mode is sent: one constructor settings read is authoritative. */
 unsetenv("UNITY_NATIVE_STARTUP_MODE");unsetenv("UNITY_NATIVE_STARTUP_PERCENT");unsetenv("UNITY_NATIVE_STARTUP_ENABLE");
 const char *foreign=getenv("LD_PRELOAD");size_t length=strlen(activation.library)+(foreign?strlen(foreign):0)+2;
 char *preload=malloc(length);if(!preload)refuse("loader environment allocation failed");
 snprintf(preload,length,"%s%s%s",activation.library,foreign&&*foreign?":":"",foreign?foreign:"");
 if(setenv("LD_PRELOAD",preload,1))refuse("cannot set native loader");free(preload);
 execve(activation.target_exe,argv,environ);refuse("cannot execute original Editor");
}
