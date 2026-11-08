#ifndef UNITY_DEFAULT_SNAPSHOT_POLICY_H
#define UNITY_DEFAULT_SNAPSHOT_POLICY_H
/* Pure policy/arithmetic ABI. No Unity calls, state, setter, allocation, GTK,
 * environment mutation, launcher, constructor or installer. */
#include <stdint.h>
#include <math.h>
#include <string.h>
#include <float.h>
#include "scale_policy.h"
#ifdef __cplusplus
extern "C" {
#endif
#define DP_POLICY_ABI 1u
enum {DP_DEFAULT=0,DP_CUSTOM=1};
enum {DP_OK=0,DP_ARGUMENT=-1,DP_UNSUPPORTED_G=-2,DP_EPOCH_RANGE=-3};
enum {DP_STOCK_ROUTE=0,DP_CUSTOM_ROUTE=1};
typedef struct {uint32_t mode,percent;double u;} dp_policy;
typedef struct {uint64_t epoch;dp_policy policy;} dp_snapshot;
/* Zero U is an intentional DEFAULT sentinel, never a factor. Only CUSTOM
 * uses U=percent/100. Mode must survive CUSTOM100<->DEFAULT, even at G1. */
static inline int dp_make(uint32_t mode,uint32_t percent,dp_policy *out){
    if(!out)return DP_ARGUMENT;
    if(mode==DP_DEFAULT&&percent==0){*out=(dp_policy){DP_DEFAULT,0,0.0};return DP_OK;}
    if(mode!=DP_CUSTOM||percent<100||percent>200)return DP_ARGUMENT;
    *out=(dp_policy){DP_CUSTOM,percent,(double)percent/100.0};return DP_OK;
}
static inline int dp_valid(dp_policy p){
    dp_policy q;return dp_make(p.mode,p.percent,&q)==DP_OK&&p.u==q.u;
}
static inline int dp_equal(dp_policy a,dp_policy b){
    return dp_valid(a)&&dp_valid(b)&&a.mode==b.mode&&a.percent==b.percent;
}
/* Suggested one-word captain publication replacing fixed150 low-bit packing.
 * Bits63..32 epoch1..UINT32_MAX, bit16 mode, bits15..0 percent, bits31..17=0.
 * Explicit overflow refusal, no epoch wrap. Captain owns atomic acquire/release.
 * ABI/storage change is internal; never reinterpret an old packed word. */
static inline int dp_encode(dp_snapshot s,uint64_t *out){
    if(!out||!dp_valid(s.policy))return DP_ARGUMENT;
    if(!s.epoch||s.epoch>UINT32_MAX)return DP_EPOCH_RANGE;
    *out=(s.epoch<<32)|((uint64_t)s.policy.mode<<16)|s.policy.percent;return DP_OK;
}
static inline int dp_decode(uint64_t packed,dp_snapshot *out){
    if(!out||(packed&UINT64_C(0xfffe0000)))return DP_ARGUMENT;
    dp_policy p;int rc=dp_make((uint32_t)((packed>>16)&1),(uint32_t)(packed&65535),&p);
    if(rc)return rc;
    uint64_t epoch=packed>>32;
    if(!epoch)return DP_EPOCH_RANGE;
    *out=(dp_snapshot){epoch,p};return DP_OK;
}
/* Parser receives explicit mode and canonical custom text. No atof/rounding
 * from a float. DEFAULT has no percent string at all (NULL only). */
static inline int dp_parse(uint32_t mode,const char *percent,dp_policy *out){
    if(mode==DP_DEFAULT)return percent?DP_ARGUMENT:dp_make(DP_DEFAULT,0,out);
    usp_scale scale;
    if(mode!=DP_CUSTOM||!usp_parse(percent,&scale))return DP_ARGUMENT;
    return dp_make(DP_CUSTOM,scale.percent,out);
}
/* Pin this entire value to the existing native operation/owner stage. A
 * separate active flag MUST be used because staged DEFAULT intentionally U0. */
typedef struct {int active;dp_snapshot value;} dp_staged;
static inline int dp_select(const dp_staged *stage,dp_snapshot published,dp_snapshot *out){
    if(!out)return DP_ARGUMENT;
    dp_snapshot s=stage&&stage->active?stage->value:published;
    if(!dp_valid(s.policy)||!s.epoch)return DP_ARGUMENT;
    *out=s;return DP_OK;
}
static inline int dp_route(dp_policy p){return dp_valid(p)?(int)p.mode:DP_ARGUMENT;}
/* Retained-stock dispatch is mandatory for DEFAULT. Do not run custom geometry,
 * player=1, integer projection, custom GPU islands or G1 guards in this mode.
 * Cache preparation needs retained ORIGINAL GetGtkWindowScale per live widget;
 * do not query the currently hooked custom function or reuse U of old epoch. */
static inline int dp_window_factors(dp_policy p,int actual_g,double stock_ppp,
                                     double *target_ppp,double *logical_per_point){
    if(!dp_valid(p)||!target_ppp||!logical_per_point)return DP_ARGUMENT;
    if(p.mode==DP_DEFAULT){
        if(!isfinite(stock_ppp)||stock_ppp<=0||stock_ppp>FLT_MAX)return DP_ARGUMENT;
        *target_ppp=stock_ppp;*logical_per_point=1.0;return DP_OK;
    }
    if(actual_g!=1)return DP_UNSUPPORTED_G;
    *target_ppp=p.u;*logical_per_point=p.u;return DP_OK;
}
/* Restore captured process-local GTK DPI value including -1 derived-policy
 * sentinel, rather than synthesizing96*100 or desktop145. Capture BEFORE any
 * app custom write; actual GtkSettings observation/restoration belongs captain. */
static inline int dp_menu_restore_value(dp_policy p,int saved_stock,int custom_value,int *out){
    if(!out||!dp_valid(p))return DP_ARGUMENT;
    *out=p.mode==DP_DEFAULT?saved_stock:custom_value;return DP_OK;
}
#ifdef __cplusplus
}
#endif
#endif
