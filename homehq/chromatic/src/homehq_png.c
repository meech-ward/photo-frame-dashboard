#include "homehq_png.h"
#include <stdlib.h>
#include <string.h>
#include "vendor/pngle/pngle.h"

struct HQ_PngStream {
    pngle_t *decoder;
    uint16_t *pixels;
    size_t total;
    size_t header_length;
    size_t remaining;
    uint32_t decoded_pixels;
    uint32_t sampled_pixels;
    bool failed;
    bool done;
    uint8_t header[33];
    uint8_t input[2048];
};

static uint32_t big_endian(const uint8_t *bytes)
{
    return ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16) |
           ((uint32_t)bytes[2] << 8) | bytes[3];
}

static bool header_valid(const uint8_t *bytes)
{
    static const uint8_t signature[] = {137, 80, 78, 71, 13, 10, 26, 10};
    /* The badge contract deliberately fixes dimensions and colour formats.
     * Checking before pngle sees IHDR prevents untrusted dimensions from
     * becoming a large scanline allocation on the MCU without PSRAM. */
    return !memcmp(bytes, signature, sizeof(signature)) &&
           big_endian(bytes + 8) == 13 && !memcmp(bytes + 12, "IHDR", 4) &&
           big_endian(bytes + 16) == 320 && big_endian(bytes + 20) == 240 &&
           bytes[24] == 8 && (bytes[25] == 2 || bytes[25] == 3 || bytes[25] == 6) &&
           bytes[26] == 0 && bytes[27] == 0 && bytes[28] == 0;
}

static uint16_t rgb565(uint8_t red, uint8_t green, uint8_t blue)
{
    return (uint16_t)(((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3));
}

static void draw_pixel(pngle_t *pngle, uint32_t x, uint32_t y,
                       uint32_t width, uint32_t height, const uint8_t rgba[4])
{
    HQ_PngStream *stream = pngle_get_user_data(pngle);
    if (x >= 320 || y >= 240 || width != 1 || height != 1) {
        stream->failed = true;
        return;
    }
    stream->decoded_pixels++;
    uint32_t dx = x * 96 / 320;
    uint32_t dy = y * HQ_PHOTO_HEIGHT / 240;
    /* Sample the centre of each destination cell while the source scanline
     * passes. A 96x72 picture preserves the source's 4:3 aspect inside the
     * 128x72 card; no 320x240 decoded framebuffer is ever retained. */
    if (x != (2 * dx + 1) * 320 / (2 * 96) ||
        y != (2 * dy + 1) * 240 / (2 * HQ_PHOTO_HEIGHT)) return;
    unsigned alpha = rgba[3];
    uint8_t red = (rgba[0] * alpha + 15 * (255 - alpha) + 127) / 255;
    uint8_t green = (rgba[1] * alpha + 23 * (255 - alpha) + 127) / 255;
    uint8_t blue = (rgba[2] * alpha + 42 * (255 - alpha) + 127) / 255;
    stream->pixels[dy * HQ_PHOTO_WIDTH + 16 + dx] = rgb565(red, green, blue);
    stream->sampled_pixels++;
}

static void done(pngle_t *pngle)
{
    HQ_PngStream *stream = pngle_get_user_data(pngle);
    stream->done = true;
}

HQ_PngStream *HQ_PngNew(uint16_t *pixels)
{
    if (!pixels) return NULL;
    HQ_PngStream *stream = calloc(1, sizeof(*stream));
    if (!stream) return NULL;
    stream->pixels = pixels;
    for (unsigned i = 0; i < HQ_PHOTO_WIDTH * HQ_PHOTO_HEIGHT; i++)
        pixels[i] = rgb565(15, 23, 42);
    return stream;
}

bool HQ_PngFeed(HQ_PngStream *stream, const uint8_t *bytes, size_t length)
{
    if (!stream || stream->failed || (!bytes && length)) return false;
    if (!length) return true;
    if (length > HQ_PHOTO_MAX_PNG - stream->total) {
        stream->failed = true;
        return false;
    }
    stream->total += length;
    if (!stream->decoder) {
        size_t take = sizeof(stream->header) - stream->header_length;
        if (take > length) take = length;
        memcpy(stream->header + stream->header_length, bytes, take);
        stream->header_length += take;
        bytes += take;
        length -= take;
        if (stream->header_length < sizeof(stream->header)) return true;
        if (!header_valid(stream->header)) {
            stream->failed = true;
            return false;
        }
        stream->decoder = pngle_new();
        if (!stream->decoder) {
            stream->failed = true;
            return false;
        }
        pngle_set_user_data(stream->decoder, stream);
        pngle_set_draw_callback(stream->decoder, draw_pixel);
        pngle_set_done_callback(stream->decoder, done);
        int fed = pngle_feed(stream->decoder, stream->header, sizeof(stream->header));
        if (fed < 0 || (size_t)fed != sizeof(stream->header)) {
            stream->failed = true;
            return false;
        }
    }
    while (length) {
        size_t take = sizeof(stream->input) - stream->remaining;
        if (take > length) take = length;
        if (!take) {
            stream->failed = true;
            return false;
        }
        memcpy(stream->input + stream->remaining, bytes, take);
        stream->remaining += take;
        bytes += take;
        length -= take;
        int fed = pngle_feed(stream->decoder, stream->input, stream->remaining);
        if (fed < 0 || stream->failed) {
            stream->failed = true;
            return false;
        }
        stream->remaining -= (size_t)fed;
        memmove(stream->input, stream->input + fed, stream->remaining);
    }
    return !stream->failed;
}

bool HQ_PngComplete(const HQ_PngStream *stream)
{
    /* pngle verifies each chunk's CRC. Counting the complete raster also
     * rejects a truncated IDAT followed by a syntactically valid IEND. */
    return stream && !stream->failed && stream->done && !stream->remaining &&
           stream->decoded_pixels == 320 * 240 &&
           stream->sampled_pixels == 96 * HQ_PHOTO_HEIGHT;
}

void HQ_PngDestroy(HQ_PngStream *stream)
{
    if (!stream) return;
    pngle_destroy(stream->decoder);
    free(stream);
}
