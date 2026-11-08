#ifndef UNITY_LAUNCH_SCALE_POLICY_H
#define UNITY_LAUNCH_SCALE_POLICY_H
/* Launch-immutable arithmetic only. No GTK calls or live transition API. */
#include <stdint.h>
#include <limits.h>
#include <math.h>
#include <string.h>

typedef struct { unsigned percent; } usp_scale;
/* Canonical integer text only, 100..200. Range is experimental admission,
 * not a claim that every admitted percentage renders correctly. */
static inline int usp_parse(const char *s, usp_scale *out) {
    if (!s || strlen(s)!=3 || s[0]<'1' || s[0]>'2' ||
        s[1]<'0' || s[1]>'9' || s[2]<'0' || s[2]>'9') return 0;
    unsigned p=(unsigned)(s[0]-'0')*100+(unsigned)(s[1]-'0')*10+(unsigned)(s[2]-'0');
    if(p<100 || p>200) return 0;
    out->percent=p; return 1;
}
/* |v| <= INT_MAX+1, numerator <=200, denominator <=200: int64 is ample.
 * Round exact rational ties away from zero, matching V4 lround intent. */
static inline int usp_ratio(int v, unsigned num, unsigned den, int *out) {
    if (!num || num>200 || !den || den>200) return 0;
    int64_t n=(int64_t)v*num;
    int64_t q=n<0?-((-n+den/2)/den):(n+den/2)/den;
    if(q<INT_MIN || q>INT_MAX) return 0;
    *out=(int)q; return 1;
}
static inline int usp_logical(usp_scale s,int p,int *out) {
    return s.percent>=100 && s.percent<=200 && usp_ratio(p,s.percent,100,out);
}
static inline int usp_points(usp_scale s,int l,int *out) {
    return s.percent>=100 && s.percent<=200 && usp_ratio(l,100,s.percent,out);
}
static inline int usp_trunc(double v,int *out) {
    if(!isfinite(v)) return 0;
    double t=trunc(v);
    if(t<INT_MIN || t>INT_MAX) return 0;
    *out=(int)t; return 1;
}
static inline int usp_add(int a,int b,int *out) {
    int64_t v=(int64_t)a+b;
    if(v<INT_MIN || v>INT_MAX)return 0;
    *out=(int)v;return 1;
}
/* GTK's automatic-size sentinel is -1; no other negatives are dimensions. */
static inline int usp_request(usp_scale s,int p,int *out) {
    if(p == -1){*out=-1;return 1;}
    return p>=0 && usp_logical(s,p,out);
}
static inline int usp_resize(usp_scale s,int p,int *out) {
    return p>0 && usp_logical(s,p,out);
}
#endif
