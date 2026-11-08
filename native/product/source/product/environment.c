#define _GNU_SOURCE
#include "environment.h"
#include "../deps/native_scope_guard.h"
#include <ctype.h>
#include <sys/stat.h>

static int own(const char*token,const char*library){
 if(!strcmp(token,library))return 1;
 /* Bare sonames use ld.so search paths, not necessarily the current directory. */
 if(!strchr(token,'/'))return 0;
 struct stat a,b;return !stat(token,&a)&&!stat(library,&b)&&a.st_dev==b.st_dev&&a.st_ino==b.st_ino;
}
static int preload(const char*library,int remove){
 const char*raw=getenv("LD_PRELOAD");if(!raw||!*raw)return 0;
 if(!library||!*library||strnlen(raw,32769)>32768)return -1;
 char*copy=strdup(raw),*result=malloc(strlen(raw)+1);if(!copy||!result){free(copy);free(result);return -1;}
 char*p=copy;size_t n=0;unsigned removed=0,foreign=0;
 while(*p){
  while(*p==':'||isspace((unsigned char)*p))p++;if(!*p)break;
  char*start=p;while(*p&&*p!=':'&&!isspace((unsigned char)*p))p++;
  char separator=*p;*p=0;
  if(own(start,library))++removed;
  else{if(n)result[n++]=' ';size_t length=strlen(start);memcpy(result+n,start,length);n+=length;++foreign;}
  if(!separator)break;++p;
 }
 result[n]=0;int rc=0;
 if(remove&&removed)rc=n?setenv("LD_PRELOAD",result,1):unsetenv("LD_PRELOAD");
 free(copy);free(result);return rc?-1:(remove?0:(int)foreign);
}
int nsp_strip_own_preload(const char*library){return preload(library,1);}
int nsp_has_foreign_preload(const char*library){return preload(library,0);}

int nsp_custom_session(void){
 const char*session=getenv("XDG_SESSION_TYPE"),*desktop=getenv("XDG_CURRENT_DESKTOP"),*display=getenv("DISPLAY");
 if(!session||strcmp(session,"wayland")||!desktop||strnlen(desktop,513)>512||!display||!*display||strnlen(display,257)>256)return -1;
 char names[513];strcpy(names,desktop);char*cursor=names,*part;int kde=0;
 while((part=strsep(&cursor,":")))if(!strcmp(part,"KDE"))kde=1;
 /* Session checks protect the native window adapter only. Graphics APIs,
  * render pipelines and launch arguments remain entirely Unity's decision. */
 return kde?0:-1;
}

int nsp_open_receipt(const char*prefix,char*actual,size_t capacity){
 if(!prefix||prefix[0]!='/'||!prefix[1]||strnlen(prefix,PATH_MAX)>=PATH_MAX){errno=EINVAL;return -1;}
 char*parts=strdup(prefix+1);if(!parts)return -1;
 int directory=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(directory<0){free(parts);return -1;}
 int result=-1;char*cursor=parts,*part;
 while((part=strsep(&cursor,"/"))){
  if(!*part||!strcmp(part,".")||!strcmp(part,"..")){errno=EINVAL;break;}
  if(cursor){
   int next=openat(directory,part,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
   if(next<0)break;close(directory);directory=next;continue;
  }
  struct stat parent;unsigned long long start;
  if(fstat(directory,&parent)||parent.st_uid!=getuid()||(parent.st_mode&0022)||usg_self_starttime(&start))break;
  char leaf[NAME_MAX+1];int size=snprintf(leaf,sizeof leaf,"%s.gui-%ld-%llu",part,(long)getpid(),start);
  if(size<0||(size_t)size>=sizeof leaf){errno=ENAMETOOLONG;break;}
  size=snprintf(actual,capacity,"%s.gui-%ld-%llu",prefix,(long)getpid(),start);
  if(size<0||(size_t)size>=capacity){errno=ENAMETOOLONG;break;}
  result=openat(directory,leaf,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);break;
 }
 close(directory);free(parts);return result;
}
