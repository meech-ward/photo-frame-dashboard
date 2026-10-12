#pragma once
#include <stdbool.h>
/* These functions belong only to the network worker. Join and changed hints
 * call ServiceRefresh; tables and normal RPC snapshots stay authoritative. */
void HQ_RTConfigure(const char *url, const char *key, const char *home, const char *jwt);
void HQ_RTStop(void);
void HQ_RTPoll(void);
bool HQ_RTJoined(void);
