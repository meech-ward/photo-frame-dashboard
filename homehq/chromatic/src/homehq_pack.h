#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
/* Factory NVS is only 24 KiB. Cache compression preserves the full 32 KiB wire
 * contract without repartitioning flash or deleting factory settings. */
uint8_t *HQ_Pack(const void *input, size_t length, size_t *packed_length);
/* No allocation: input and output must be separate buffers. On failure the
 * output may contain a prefix, but packed_length is zero and cannot be stored. */
bool HQ_PackInto(const void *input, size_t length, void *output, size_t capacity,
                 size_t *packed_length);
char *HQ_Unpack(const void *input, size_t length, size_t *unpacked_length);
