#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

#define HQ_PHOTO_RANGE_MAX 327680u
#define HQ_PHOTO_RANGE_CHUNK 4096u
#define HQ_PHOTO_ETAG_MAX 96u

static inline bool hq_photo_range_number(const char **cursor, size_t *number)
{
    const char *p = *cursor, *begin = p;
    size_t value = 0;
    while (*p >= '0' && *p <= '9') {
        unsigned digit = (unsigned)(*p - '0');
        /* Reject before arithmetic: no field can exceed the badge's 320 KiB
         * contract, including arbitrarily long decimal overflow strings. */
        if (value > (HQ_PHOTO_RANGE_MAX - digit) / 10u) return false;
        value = value * 10u + digit; ++p;
    }
    if (p == begin) return false;
    *cursor = p; *number = value; return true;
}

static inline bool HQ_PhotoRangeParse(const char *value, size_t expected_start,
                                      size_t requested_end, size_t fixed_total,
                                      size_t *total, size_t *length)
{
    if (!total || !length || total == length) return false;
    *total = *length = 0;
    if (!value || strncmp(value, "bytes ", 6) || expected_start >= HQ_PHOTO_RANGE_MAX ||
        requested_end < expected_start || requested_end - expected_start >= HQ_PHOTO_RANGE_CHUNK ||
        fixed_total > HQ_PHOTO_RANGE_MAX) return false;
    const char *p = value + 6;
    size_t first, last, size;
    if (!hq_photo_range_number(&p, &first) || *p++ != '-' ||
        !hq_photo_range_number(&p, &last) || *p++ != '/' ||
        !hq_photo_range_number(&p, &size) || *p || !size ||
        first != expected_start || first > last || last >= size ||
        (fixed_total && size != fixed_total)) return false;
    size_t final = requested_end < size - 1 ? requested_end : size - 1;
    /* A truncated object legitimately shortens only its final range. A wrong
     * endpoint cannot silently append a gap/overlap to the staged PNG. */
    if (last != final) return false;
    *total = size; *length = last - first + 1; return true;
}

static inline bool HQ_PhotoETagValid(const char *value)
{
    if (!value || value[0] != '"') return false;
    size_t length = 0;
    while (length <= HQ_PHOTO_ETAG_MAX && value[length]) ++length;
    if (length < 2 || length > HQ_PHOTO_ETAG_MAX || value[length - 1] != '"') return false;
    /* A strong validator keeps the private object consistent across ranges.
     * Bound copied metadata and reject controls/interior quotes rather than
     * letting them become request lines. */
    for (size_t i = 1; i < length - 1; ++i) {
        unsigned char c = (unsigned char)value[i];
        if (c < 0x21 || c > 0x7e || c == '"') return false;
    }
    return true;
}
