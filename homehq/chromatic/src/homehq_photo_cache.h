#pragma once
#include <stdbool.h>
#include <stdint.h>

#define HQ_PHOTO_CACHE_WIDTH 128u
#define HQ_PHOTO_CACHE_HEIGHT 72u
#define HQ_PHOTO_CACHE_BYTES (HQ_PHOTO_CACHE_WIDTH * HQ_PHOTO_CACHE_HEIGHT * 2u)
typedef bool (*HQ_PhotoCacheGuard)(void *context);

/* Worker-only, serialized with account clearing. The service must check its
 * identity generation before these calls and before publishing loaded pixels.
 * Pixels use canonical RGB565 little endian, before any LVGL byte swap. Cache
 * failures leave ordinary authenticated download/RAM display available. */
bool HQ_PhotoCacheLoad(const char *user, const char *path, uint16_t *pixels,
                      HQ_PhotoCacheGuard guard, void *context);
bool HQ_PhotoCacheSave(const char *user, const char *path, const uint16_t *pixels,
                      HQ_PhotoCacheGuard guard, void *context);
bool HQ_PhotoCacheDrop(void);
