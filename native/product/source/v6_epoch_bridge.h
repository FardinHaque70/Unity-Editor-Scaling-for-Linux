#pragma once
#include "deps/epoch.h"
/* One launch-immutable canonical float PPP widened to double. No hot setter,
 * TLS staging, managed provider, socket dispatch or production lease. */
#ifdef __cplusplus
extern "C" {
#endif
int v6_conversion_snapshot(ep_snapshot*);
int v6_conversion_snapshot_site(unsigned,ep_snapshot*);
#ifdef __cplusplus
}
#endif
