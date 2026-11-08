#include "accepted_content.h"
#include <math.h>
#include <string.h>
static int identity_equal(const cg_identity*a,const cg_identity*b){
 return a->native==b->native&&a->generation==b->generation&&a->mode==b->mode&&
        a->top==b->top&&a->fixed==b->fixed&&a->menubar==b->menubar;
}
static int valid(const cg_widget*w,int kind){return w->mapped&&w->g==1&&w->kind==kind&&w->allocation.w>0&&w->allocation.h>0;}
int cg_read(const cg_host*h,uint64_t native,uint64_t generation,float u,cg_sample*out){
 if(!out)return CG_ARGUMENT;
 memset(out,0,sizeof(*out));
 if(!h||!h->resolve||!h->parent||!h->widget||!h->window||!h->origin||!native||!generation||(!isfinite(u)||u<1||u>2))return CG_ARGUMENT;
 cg_identity id={0},after={0};int rc=h->resolve(h->context,native,generation,&id);
 if(rc)return rc;
 if(id.native!=native||id.generation!=generation||!id.top||!id.fixed)return CG_STALE;
 if(id.mode!=0&&id.mode!=4)return CG_MODE;
 void*viewport=h->parent(h->context,id.fixed);
 void*content=viewport?h->parent(h->context,viewport):0;
 if(!viewport||!content)return CG_CHART;
 cg_widget f={0},v={0},c={0},m={0};cg_rect top={0};int32_t origin[2]={0};
 if(h->widget(h->context,id.fixed,&f)||h->widget(h->context,viewport,&v)||
    h->widget(h->context,content,&c)||h->window(h->context,id.top,&top))return CG_NOT_READY;
 if(!valid(&f,CG_FIXED)||!valid(&v,CG_VIEWPORT)||!valid(&c,CG_SCROLLED)||top.w<1||top.h<1)return CG_CHART;
 /* Exact supported no-frame/no-scrollbar chart. Capture actual allocations;
  * do not guess away a new border/margin/scrollbar discrepancy. */
 if(v.allocation.x||v.allocation.y||c.allocation.x||c.allocation.w!=v.allocation.w||c.allocation.h!=v.allocation.h||
    c.allocation.w!=top.w||f.allocation.w<c.allocation.w||f.allocation.h<c.allocation.h)return CG_CHART;
 if(id.mode==4){
  if(!id.menubar||h->widget(h->context,id.menubar,&m)||!valid(&m,CG_MENUBAR))return CG_NOT_READY;
  if(c.allocation.y!=m.allocation.h||(int64_t)c.allocation.h+m.allocation.h!=top.h)return CG_CHART;
 }else{
  /* Floater managed root includes Unity DockArea tabs; no native menu subtract.
   * Do not silently change original mode0 fixed/root semantics on an oversized
   * fixed. Refuse that as a new runtime chart until measured and reviewed. */
  if(id.menubar||f.allocation.x||f.allocation.y||c.allocation.y||c.allocation.h!=top.h||f.allocation.w!=c.allocation.w||f.allocation.h!=c.allocation.h)return CG_CHART;
 }
 /* Preserve original GetTopleftScreenPosition mode choice independently from
  * GTK top-level position/gravity. Never add allocation-local x/y to a root. */
 if(h->origin(h->context,id.mode==4?content:id.fixed,origin))return CG_NOT_READY;
 rc=h->resolve(h->context,native,generation,&after);
 if(rc)return rc;
 if(!identity_equal(&id,&after))return CG_STALE;
 cg_sample s={0};s.abi=CG_ABI;s.size=sizeof(s);s.native=native;s.generation=generation;s.mode=id.mode;s.target_u=u;
 s.top_position_size_L=top;s.fixed_L=f.allocation;s.viewport_L=v.allocation;s.content_L=c.allocation;s.menu_L=m.allocation;
 memcpy(s.original_screen_origin_L,origin,sizeof(origin));memcpy(s.cached_points,id.cached_points,sizeof(s.cached_points));
 s.target_container_points[0]=(float)((double)top.x/u);s.target_container_points[1]=(float)((double)top.y/u);
 s.target_container_points[2]=(float)((double)c.allocation.w/u);s.target_container_points[3]=(float)((double)c.allocation.h/u);
 s.target_root_points[2]=s.target_container_points[2];s.target_root_points[3]=s.target_container_points[3];
 s.target_original_screen_origin_points[0]=(float)((double)origin[0]/u);s.target_original_screen_origin_points[1]=(float)((double)origin[1]/u);
 s.menu_height_points=id.mode==4?(int32_t)lround((double)m.allocation.h/u):0;
 s.fixed_larger_than_visible=(f.allocation.w!=c.allocation.w||f.allocation.h!=c.allocation.h);
 *out=s;return CG_OK;
}
