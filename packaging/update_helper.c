/* Self-contained signed-update verifier and short-lived replacement helper.
 * Build statically with OpenSSL libcrypto; no Python/mounted files
 * are needed after the settings process exits. Never launches Unity. */
#define _GNU_SOURCE
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <regex.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/file.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define IMAGE "Unity-Editor-Scaling-for-Linux-x86_64.AppImage"
static int regular(const char *p) {
    struct stat s;
    return lstat(p, &s)==0 && S_ISREG(s.st_mode) && s.st_uid==getuid() && !(s.st_mode&0022);
}
static unsigned char *readfile(const char *p, size_t cap, size_t *length) {
    int fd=open(p,O_RDONLY|O_NOFOLLOW|O_CLOEXEC); struct stat s;
    if(fd<0) return NULL;
    if(fstat(fd,&s)||!S_ISREG(s.st_mode)||s.st_size<0||(unsigned long long)s.st_size>cap) {close(fd); return NULL;}
    size_t n=(size_t)s.st_size, off=0; unsigned char *b=malloc(n+1);
    if(!b) {close(fd);return NULL;}
    while(off<n) {ssize_t r=read(fd,b+off,n-off); if(r<=0){free(b);close(fd);return NULL;}off+=(size_t)r;}
    close(fd);b[n]=0;*length=n;return b;
}
static unsigned char *verified(const char *keypath,const char *manifest,const char *sigpath,size_t *len) {
    size_t sn=0; unsigned char *m=readfile(manifest,16384,len),*sig=readfile(sigpath,64,&sn);
    FILE *key=fopen(keypath,"r"); EVP_PKEY *pk=key?PEM_read_PUBKEY(key,NULL,NULL,NULL):NULL;
    if(key)fclose(key);
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();
    int ok=m&&sig&&sn==64&&pk&&ctx&&EVP_PKEY_id(pk)==EVP_PKEY_ED25519&&
        EVP_DigestVerifyInit(ctx,NULL,NULL,NULL,pk)==1&&EVP_DigestVerify(ctx,sig,sn,m,*len)==1;
    EVP_MD_CTX_free(ctx);EVP_PKEY_free(pk);free(sig);
    if(!ok){free(m);return NULL;}return m;
}
/* Fixed signed schema: all string fields are plain ASCII. Escape sequences,
 * duplicate/unknown keys, embedded NUL and extra JSON values are rejected. */
struct document { const unsigned char *p,*end; };
static void space(struct document *d){while(d->p<d->end&&(*d->p==' '||*d->p=='\n'||*d->p=='\r'||*d->p=='\t'))d->p++;}
static int take(struct document *d,int c){space(d);if(d->p==d->end||*d->p!=c)return 0;d->p++;return 1;}
static int string(struct document *d,char *out,size_t cap){
    if(!take(d,'"'))return 0;
    size_t n=0;
    while(d->p<d->end&&*d->p!='"'){
      if(*d->p<32||*d->p>126||*d->p=='\\'||n+1>=cap)return 0;
      out[n++]=(char)*d->p++;
    }
    if(d->p==d->end)return 0;
    d->p++;out[n]=0;return 1;
}
static int number(struct document *d,long long *value){
    space(d);*value=0;if(d->p==d->end||*d->p<'0'||*d->p>'9')return 0;
    int zero=*d->p=='0';int digits=0;
    while(d->p<d->end&&*d->p>='0'&&*d->p<='9'){
      if((zero&&digits)||*value>1073741824)return 0;
      *value=*value*10+(*d->p++-'0');digits++;
    }
    return *value<=1073741824;
}
static int schema(const unsigned char *m,size_t len,const char *expected_version,long long *size,char hash[65]){
    struct document d={m,m+len};char key[32],text[128],version[80]="",channel[20]="";
    unsigned int seen=0;
    if(!take(&d,'{'))return 0;
    for(int count=0;count<7;count++){
      if(count&&!take(&d,','))return 0;
      if(!string(&d,key,sizeof(key))||!take(&d,':'))return 0;
      const char *names[]={"schema","version","channel","architecture","filename","size","sha256"};
      int index=0;for(;index<7;index++)if(!strcmp(key,names[index]))break;
      if(index==7||(seen&(1u<<index)))return 0;
      seen|=1u<<index;
      if(index==0||index==5){long long value;if(!number(&d,&value))return 0;
        if(index==0&&value!=1)return 0;
        if(index==5){if(value<=0)return 0;*size=value;}
      }else{
        if(!string(&d,text,sizeof(text)))return 0;
        if(index==1){if(strlen(text)>=sizeof(version))return 0;strcpy(version,text);}
        if(index==2){if(strlen(text)>=sizeof(channel))return 0;strcpy(channel,text);}
        if(index==3&&strcmp(text,"x86_64"))return 0;
        if(index==4&&strcmp(text,IMAGE))return 0;
        if(index==6){if(strlen(text)!=64)return 0;strcpy(hash,text);
          for(int i=0;i<64;i++)if(!((hash[i]>='0'&&hash[i]<='9')||(hash[i]>='a'&&hash[i]<='f')))return 0;}
      }
    }
    if(seen!=127||!take(&d,'}'))return 0;
    space(&d);if(d.p!=d.end||strcmp(version,expected_version))return 0;
    regex_t rx;
    if(regcomp(&rx,"^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(-rc\\.(0|[1-9][0-9]*))?$",REG_EXTENDED|REG_NOSUB))return 0;
    int valid=regexec(&rx,version,0,NULL,0)==0;regfree(&rx);
    return valid&&!strcmp(channel,strstr(version,"-rc.")?"prerelease":"stable");
}
static int payload(const unsigned char *m,size_t len,const char *image,const char *version) {
    long long size=0;char expected[65];int ok=schema(m,len,version,&size,expected);
    int fd=ok?open(image,O_RDONLY|O_NOFOLLOW|O_CLOEXEC):-1;struct stat st;
    if(fd<0||fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid!=getuid()||(st.st_mode&0022)||st.st_size!=size)ok=0;
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();unsigned char bytes[131072],digest[32];unsigned int dlen=0;char hex[65];
    if(ok&&ctx&&EVP_DigestInit_ex(ctx,EVP_sha256(),NULL)==1){
      ssize_t n;while((n=read(fd,bytes,sizeof(bytes)))>0)if(EVP_DigestUpdate(ctx,bytes,(size_t)n)!=1){ok=0;break;}
      if(n<0||EVP_DigestFinal_ex(ctx,digest,&dlen)!=1||dlen!=32)ok=0;
      if(ok){for(int i=0;i<32;i++)sprintf(hex+i*2,"%02x",digest[i]);if(strcmp(hex,expected))ok=0;}
    }else ok=0;
    if(fd>=0)close(fd);
    EVP_MD_CTX_free(ctx);return ok;
}
/* Durable transaction metadata lets the next startup recover a process/power
 * interruption. The candidate remains bound to its signed manifest; the old
 * payload hash prevents restoration of an unrelated rollback file. */
static int filehash(const char *path,char hex[65]){
    int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return 0;
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();unsigned char buf[131072],hash[32];unsigned int count=0;
    int ok=ctx&&EVP_DigestInit_ex(ctx,EVP_sha256(),NULL)==1;ssize_t n=0;
    while(ok&&(n=read(fd,buf,sizeof(buf)))>0)ok=EVP_DigestUpdate(ctx,buf,(size_t)n)==1;
    if(n<0||!ok||EVP_DigestFinal_ex(ctx,hash,&count)!=1||count!=32)ok=0;
    if(ok)for(int i=0;i<32;i++)sprintf(hex+i*2,"%02x",hash[i]);
    EVP_MD_CTX_free(ctx);close(fd);return ok;
}
static int transaction(const char *dir,const char *target,const char *manifest,const char *signature,
                       const char *key,const char *version,const char *token,const char *newhash){
    char oldhash[65],path[PATH_MAX],json[512];if(!filehash(target,oldhash))return 0;
    const char *durable[]={manifest,signature,key};
    for(int i=0;i<3;i++){int fd=open(durable[i],O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return 0;
      int failed=fsync(fd);close(fd);if(failed)return 0;}
    if(snprintf(path,sizeof(path),"%s/transaction.json",dir)>=(int)sizeof(path))return 0;
    int n=snprintf(json,sizeof(json),"{\"schema\":1,\"old_sha256\":\"%s\",\"new_sha256\":\"%s\",\"version\":\"%s\",\"token\":\"%s\"}\n",oldhash,newhash,version,token);
    if(n<0||n>=(int)sizeof(json))return 0;
    int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return 0;
    int ok=write(fd,json,(size_t)n)==n&&fsync(fd)==0;close(fd);return ok;
}
static int syncdir(const char *p){int fd=open(p,O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0)return -1;int r=fsync(fd);close(fd);return r;}
static void start_environment(void){
    const char *keys[]={"APPIMAGE","APPDIR","ARGV0","PYTHONHOME","PYTHONPATH","GI_TYPELIB_PATH",
        "GIO_MODULE_DIR","GIO_EXTRA_MODULES","GTK_DATA_PREFIX","GSETTINGS_SCHEMA_DIR","SSL_CERT_FILE",
        "GDK_PIXBUF_MODULEDIR","GDK_PIXBUF_MODULE_FILE",NULL};
    for(int i=0;keys[i];i++)unsetenv(keys[i]);
    const char *names[]={"LD_LIBRARY_PATH","PATH","XDG_DATA_DIRS","FONTCONFIG_FILE","FONTCONFIG_PATH"};
    const char *saved[]={"UNITY_SCALE_HOST_LD_LIBRARY_PATH","UNITY_SCALE_HOST_PATH","UNITY_SCALE_HOST_XDG_DATA_DIRS",
        "UNITY_SCALE_HOST_FONTCONFIG_FILE","UNITY_SCALE_HOST_FONTCONFIG_PATH"};
    for(int i=0;i<5;i++){
      const char *value=getenv(saved[i]);
      if(value&&*value)setenv(names[i],value,1);else if(i!=1)unsetenv(names[i]);
      unsetenv(saved[i]);
    }
}
static pid_t launch(const char *image,const char *ack,const char *token){
    pid_t p=fork();if(p==0){start_environment();
      execl(image,image,"--install-user","--post-update",ack,token,(char*)NULL);_exit(127);}return p;
}
static void restore_launch(const char *image){pid_t p=fork();if(p==0){start_environment();execl(image,image,"--install-user","--recover-update",(char*)NULL);_exit(127);}}
static void cleanup(const char *dir){const char *files[]={"new.AppImage","release.json","release.json.sig","public-key.pem","healthy","update-helper","transaction.json","owner.json",NULL};char path[PATH_MAX];for(int i=0;files[i];i++){snprintf(path,sizeof(path),"%s/%s",dir,files[i]);unlink(path);}rmdir(dir);}
int main(int argc,char **argv){
    if(argc==5&&!strcmp(argv[1],"verify")){size_t len=0;unsigned char *m=verified(argv[2],argv[3],argv[4],&len);if(!m)return 1;free(m);return 0;}
    if(argc!=11||strcmp(argv[1],"apply"))return 2;
    char *end=NULL;long parent=strtol(argv[2],&end,10);if(*end||parent<2||parent>INT_MAX)return 2;
    const char *target=argv[3],*stage=argv[4],*manifest=argv[5],*signature=argv[6],*key=argv[7],*ack=argv[8],*token=argv[9],*version=argv[10];
    if(strlen(token)!=64)return 2;
    for(int i=0;i<64;i++)if(!((token[i]>='0'&&token[i]<='9')||(token[i]>='a'&&token[i]<='f')))return 2;
    char directory[PATH_MAX],base[PATH_MAX],rollback[PATH_MAX],expected[PATH_MAX];
    if(strlen(stage)>=sizeof(directory)||strlen(target)>=sizeof(base))return 2;
    strcpy(directory,stage);char *slash=strrchr(directory,'/');if(!slash||strcmp(slash,"/new.AppImage"))return 2;*slash=0;
    strcpy(base,target);slash=strrchr(base,'/');if(!slash||strcmp(slash,"/application.AppImage"))return 2;*slash=0;
    if(strncmp(directory,base,strlen(base))||strncmp(directory+strlen(base),"/.update-",9)||strchr(directory+strlen(base)+1,'/'))return 2;
    struct stat ds;if(lstat(directory,&ds)||!S_ISDIR(ds.st_mode)||ds.st_uid!=getuid()||(ds.st_mode&0077))return 2;
    const char *names[]={"release.json","release.json.sig","public-key.pem","healthy"};const char *paths[]={manifest,signature,key,ack};
    for(int i=0;i<4;i++){if(snprintf(expected,sizeof(expected),"%s/%s",directory,names[i])>=(int)sizeof(expected)||strcmp(expected,paths[i]))return 2;}
    if(snprintf(rollback,sizeof(rollback),"%s.rollback",target)>=(int)sizeof(rollback))return 2;
    /* Directory lock prevents concurrent update swaps without a persistent service. */
    int lock=open(base,O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(lock<0||flock(lock,LOCK_EX|LOCK_NB))return 2;
    for(int n=0;n<1200&&kill((pid_t)parent,0)==0;n++)usleep(100000);
    if(kill((pid_t)parent,0)==0){cleanup(directory);return 1;}
    size_t len=0;unsigned char *m=verified(key,manifest,signature,&len);
    long long newsize=0;char newhash[65];
    int valid=m&&regular(target)&&regular(stage)&&schema(m,len,version,&newsize,newhash)&&payload(m,len,stage,version);free(m);
    if(!valid){cleanup(directory);return 1;}
    if(!transaction(directory,target,manifest,signature,key,version,token,newhash)||syncdir(directory)||syncdir(base)){
      cleanup(directory);return 1;}
    struct stat old;if(lstat(rollback,&old)==0){cleanup(directory);return 1;}
    /* Preserve one old inode, then atomically replace the public image. */
    if(errno!=ENOENT||link(target,rollback)){cleanup(directory);return 1;}
    if(rename(stage,target)){unlink(rollback);syncdir(base);cleanup(directory);return 1;}
    syncdir(base);pid_t child=launch(target,ack,token);int healthy=0,status=0,live=child>0;
    for(int n=0;child>0&&n<1800;n++){
      size_t got=0;unsigned char *a=readfile(ack,64,&got);healthy=a&&got==64&&!memcmp(a,token,64);free(a);if(healthy)break;
      pid_t state=waitpid(child,&status,WNOHANG);
      if(state==child||(state<0&&errno==ECHILD)){live=0;break;}
      usleep(100000);
    }
    if(healthy){unlink(rollback);syncdir(base);cleanup(directory);return 0;}
    if(live){
      kill(child,SIGTERM);
      for(int n=0;n<30;n++){
        pid_t state=waitpid(child,&status,WNOHANG);
        if(state==child||(state<0&&errno==ECHILD)){live=0;break;}
        usleep(100000);
      }
      if(live){kill(child,SIGKILL);while(waitpid(child,&status,0)<0&&errno==EINTR){}}
    }
    if(rename(rollback,target)==0){syncdir(base);restore_launch(target);}
    cleanup(directory);return 1;
}
