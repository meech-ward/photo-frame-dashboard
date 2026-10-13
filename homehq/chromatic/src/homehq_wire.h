#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef struct { char home[96], viewer[96]; int64_t revision, server_time; bool demo; } HQ_WireInfo;
/* Validate the entire bounded JSON document without constructing its graph.
 * Only household/viewer metadata is extracted; the UI owns the sole cJSON tree. */
bool HQ_WireValidate(const char *wire, size_t length, HQ_WireInfo *info);
/* Direct membership in one root collection; nested objects' ids cannot keep a
 * deleted checklist row alive. Input is validated without a second cJSON tree. */
bool HQ_WireHasRow(const char *wire, size_t length, const char *section, const char *id);
