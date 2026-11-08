#define _GNU_SOURCE
#include "activation.h"
#include <errno.h>
#include <fcntl.h>
#include <json-c/json.h>
#include <openssl/evp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
extern int ups_strict_document(const char*,size_t,struct json_object**);
static nsa_config current;
const nsa_config *nsa_current(void){return &current;}
void nsa_use(const nsa_config *config){current=*config;}
static int spelling(const char*p){
 if(!p||p[0]!='/'||!p[1]||strnlen(p,PATH_MAX)>=PATH_MAX)return 0;
 for(const char*s=p+1,*a=s;;s++)if(!*s||*s=='/'){size_t n=(size_t)(s-a);if(!n||(n==1&&*a=='.')||(n==2&&a[0]=='.'&&a[1]=='.'))return 0;if(!*s)break;a=s+1;}
 return 1;
}
/* Parent components cannot be symlinks or writable by other users. Nonwritable
 * ancestors and sticky temporary parents are allowed; the package and each
 * managed file must separately be owned by the caller. */
static int secure_open(const char*path,int directory){
 if(!spelling(path))return -1;
 char copy[PATH_MAX];strcpy(copy,path+1);char*cursor=copy,*part;
 int fd=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0)return -1;
 while((part=strsep(&cursor,"/"))){
  int next=openat(fd,part,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK|((cursor||directory)?O_DIRECTORY:0));close(fd);fd=next;
  struct stat st;if(fd<0||fstat(fd,&st)){if(fd>=0)close(fd);return -1;}
  if(cursor||directory){if(!S_ISDIR(st.st_mode)||((st.st_mode&0022)&&!(st.st_mode&S_ISVTX))){close(fd);return -1;}}
 }
 return fd;
}
static int unchanged(const struct stat*a,const struct stat*b){return a->st_dev==b->st_dev&&a->st_ino==b->st_ino&&a->st_size==b->st_size&&a->st_uid==b->st_uid&&a->st_mode==b->st_mode&&a->st_mtim.tv_sec==b->st_mtim.tv_sec&&a->st_mtim.tv_nsec==b->st_mtim.tv_nsec&&a->st_ctim.tv_sec==b->st_ctim.tv_sec&&a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;}
static int safe_file(int fd,struct stat*st){return fd>=0&&!fstat(fd,st)&&S_ISREG(st->st_mode)&&st->st_uid==getuid()&&!(st->st_mode&0022)&&st->st_size>0;}
int nsa_hash(const char*path,const char*expected){
 int fd=secure_open(path,0);struct stat a,b;if(!safe_file(fd,&a)){if(fd>=0)close(fd);return -1;}
 EVP_MD_CTX*c=EVP_MD_CTX_new();int ok=c&&EVP_DigestInit_ex(c,EVP_sha256(),NULL);unsigned char buffer[65536],digest[32];ssize_t n;unsigned count=0;
 while(ok&&(n=read(fd,buffer,sizeof buffer))!=0){if(n<0){if(errno==EINTR)continue;ok=0;break;}ok=EVP_DigestUpdate(c,buffer,(size_t)n);}
 if(ok)ok=EVP_DigestFinal_ex(c,digest,&count);if(c)EVP_MD_CTX_free(c);
 if(fstat(fd,&b)||!unchanged(&a,&b))ok=0;close(fd);char hex[65]={0};if(ok&&count==32)for(unsigned i=0;i<32;i++)snprintf(hex+2*i,3,"%02x",digest[i]);
 return ok&&count==32&&!strcmp(hex,expected)?0:-1;
}
static int path_join(char*out,const char*base,const char*leaf){int n=snprintf(out,PATH_MAX,"%s/%s",base,leaf);return n<0||n>=PATH_MAX?-1:0;}
int nsa_paths(const char*own,int launcher,nsa_config*out){
 memset(out,0,sizeof *out);if(!spelling(own))return -1;
 char parent[PATH_MAX];strcpy(parent,own);char*slash=strrchr(parent,'/');if(!slash||slash==parent)return -1;*slash=0;
 if(launcher){if(strcmp(slash+1,"Unity"))return -1;if(path_join(out->package,parent,".unity-editor-scaling"))return -1;}
 else {if(strcmp(slash+1,"native-v2.so"))return -1;strcpy(out->package,parent);slash=strrchr(parent,'/');if(!slash||strcmp(slash+1,".unity-editor-scaling"))return -1;*slash=0;}
 if(path_join(out->public_editor,parent,"Unity")||path_join(out->target_exe,parent,".Unity.unity-scale-original")||path_join(out->library,out->package,"native-v2.so")||path_join(out->wrapper,out->package,"wrapper-v2"))return -1;
 return 0;
}
static int text(struct json_object*j,const char*k,char*out,size_t cap){struct json_object*v;if(!json_object_object_get_ex(j,k,&v)||!v||json_object_get_type(v)!=json_type_string)return -1;const char*s=json_object_get_string(v);size_t n=strlen(s);if(n!=(size_t)json_object_get_string_len(v)||n>=cap)return -1;memcpy(out,s,n+1);return 0;}
static int number(struct json_object*j,const char*k,unsigned long long*out){struct json_object*v;if(!json_object_object_get_ex(j,k,&v)||!v||json_object_get_type(v)!=json_type_int||json_object_get_int64(v)<0)return -1;*out=json_object_get_uint64(v);return 0;}
static int equal(struct json_object*j,const char*k,const char*value){char data[PATH_MAX];return text(j,k,data,sizeof data)||strcmp(data,value);}
static int sha_valid(const char*s){if(strlen(s)!=64)return 0;for(unsigned i=0;i<64;i++)if(!strchr("0123456789abcdef",s[i]))return 0;return 1;}
int nsa_validate(nsa_config*c){
 char descriptor[PATH_MAX];if(path_join(descriptor,c->package,"activation.json"))return -1;
 int dir=secure_open(c->package,1);struct stat st;int ok=dir>=0&&!fstat(dir,&st)&&st.st_uid==getuid()&&!(st.st_mode&0077);if(dir>=0)close(dir);if(!ok)return -1;
 int fd=secure_open(descriptor,0);struct stat before,after;if(!safe_file(fd,&before)||before.st_size>65536){if(fd>=0)close(fd);return -1;}
 char data[65537];size_t have=0;while(have<(size_t)before.st_size){ssize_t n=read(fd,data+have,(size_t)before.st_size-have);if(n<0&&errno==EINTR)continue;if(n<=0){close(fd);return -1;}have+=(size_t)n;}
 ok=!fstat(fd,&after)&&unchanged(&before,&after);close(fd);if(!ok)return -1;
 struct json_object*j=NULL,*identity=NULL;unsigned long long schema=0,uid=0;
 if(ups_strict_document(data,have,&j)||json_object_get_type(j)!=json_type_object){if(j)json_object_put(j);return -1;}
 ok=!number(j,"schema",&schema)&&schema==2&&!number(j,"owner_uid",&uid)&&uid==getuid()&&!equal(j,"constructor_contract","product-profile-v2")&&!equal(j,"public_editor",c->public_editor)&&!equal(j,"target_exe",c->target_exe)&&!equal(j,"wrapper","wrapper-v2")&&!equal(j,"library","native-v2.so")&&!equal(j,"original_sha256",NSA_ORIGINAL_SHA)&&!text(j,"settings",c->settings,sizeof c->settings)&&spelling(c->settings)&&!text(j,"library_sha256",c->library_sha256,65)&&sha_valid(c->library_sha256)&&!text(j,"wrapper_sha256",c->wrapper_sha256,65)&&sha_valid(c->wrapper_sha256)&&json_object_object_get_ex(j,"original_identity",&identity)&&identity&&json_object_get_type(identity)==json_type_object;
 if(ok)ok=!number(identity,"st_dev",&c->dev)&&!number(identity,"st_ino",&c->ino)&&!number(identity,"st_size",&c->size)&&!number(identity,"st_mtime_ns",&c->mtime_ns);
 json_object_put(j);if(!ok)return -1;
 fd=secure_open(c->target_exe,0);ok=safe_file(fd,&st)&&!!(st.st_mode&0111)&&c->dev==(unsigned long long)st.st_dev&&c->ino==(unsigned long long)st.st_ino&&c->size==(unsigned long long)st.st_size&&c->mtime_ns==(unsigned long long)st.st_mtim.tv_sec*1000000000ULL+(unsigned long long)st.st_mtim.tv_nsec;if(fd>=0)close(fd);if(!ok)return -1;
 /* Full original verification applies equally to Default and helper launcher
  * execution; no descriptor can nominate another original or package binary. */
 return nsa_hash(c->target_exe,NSA_ORIGINAL_SHA)||nsa_hash(c->public_editor,c->wrapper_sha256)||nsa_hash(c->wrapper,c->wrapper_sha256)||nsa_hash(c->library,c->library_sha256)?-1:0;
}
