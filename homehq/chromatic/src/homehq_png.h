#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define HQ_PHOTO_WIDTH 128
#define HQ_PHOTO_HEIGHT 72
#define HQ_PHOTO_BYTES (HQ_PHOTO_WIDTH * HQ_PHOTO_HEIGHT * sizeof(uint16_t))
#define HQ_PHOTO_MAX_PNG 327680

typedef struct HQ_PngStream HQ_PngStream;
/* Output is RGB565 at panel resolution. Feed accepts arbitrarily small network
 * fragments and rejects an out-of-contract IHDR before allocating the decoder. */
HQ_PngStream *HQ_PngNew(uint16_t *pixels);
bool HQ_PngFeed(HQ_PngStream *stream, const uint8_t *bytes, size_t length);
bool HQ_PngComplete(const HQ_PngStream *stream);
void HQ_PngDestroy(HQ_PngStream *stream);
