#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define HQ_PHOTO_STAGE_START 0x11a000u
#define HQ_PHOTO_STAGE_PAYLOAD 0x11b000u
#define HQ_PHOTO_STAGE_END 0x16b000u
#define HQ_PHOTO_STAGE_MAX 327680u
typedef bool (*HQ_PhotoStageGuard)(void *context);

/* Sole worker only. Begin binds one guard/context transaction; no read is
 * available before a verified Finish. Drop invalidates RAM and the own header.
 * There are no borrowed pixel/wire pointers or large allocations in this API. */
bool HQ_PhotoStageBegin(HQ_PhotoStageGuard guard, void *context);
bool HQ_PhotoStageWrite(const void *bytes, size_t length, HQ_PhotoStageGuard guard, void *context);
bool HQ_PhotoStageFinish(size_t *length, HQ_PhotoStageGuard guard, void *context);
bool HQ_PhotoStageRead(size_t offset, void *bytes, size_t length, HQ_PhotoStageGuard guard, void *context);
bool HQ_PhotoStageDrop(void);
