#pragma once
#include <stdbool.h>
#include <stddef.h>
/* Compact caller-owned canonical JSON in place. Values remain byte-identical;
 * the service's canonical wire is never modified. No allocator is used here. */
bool HQ_ProjectWire(char *wire, size_t length, const char *page);
/* Measure from a stable const source, then allocate only projected bytes plus
 * NUL. Caller owns the result; NULL never changes or frees canonical input. */
char *HQ_ProjectCopy(const char *canonical, size_t length, const char *page);
