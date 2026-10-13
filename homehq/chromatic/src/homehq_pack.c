#include "homehq_pack.h"
#include <stdlib.h>
#include <string.h>
#define LIMIT 32768u
bool HQ_PackInto(const void *input, size_t n, void *output, size_t capacity,
                 size_t *result)
{
    if (!result) return false;
    *result = 0;
    if (!input || !output || n > LIMIT || capacity < 6) return false;
    const uint8_t *src = input;
    uint8_t *out = output;
    out[0] = 'H';
    out[1] = 'Q';
    out[2] = 1;
    out[3] = 0;
    out[4] = n & 255;
    out[5] = n >> 8;
    size_t i = 0, w = 6;
    while (i < n) {
        if (w >= capacity) return false;
        size_t flag = w++;
        out[flag] = 0;
        for (unsigned bit = 0; bit < 8 && i < n; ++bit) {
            size_t best = 0, distance = 0, start = i > 4096 ? i - 4096 : 0;
            /* Long repeated keys dominate JSON. A bounded dictionary keeps
             * this worker-only pass independent of input size squared. */
            for (size_t j = i; j > start;) {
                --j;
                if (src[j] != src[i]) continue;
                size_t k = 1;
                while (k < 18 && i + k < n && src[j + k] == src[i + k]) ++k;
                if (k > best) {
                    best = k;
                    distance = i - j;
                    if (k == 18) break;
                }
            }
            if (best >= 3) {
                /* The live heap had 84 KiB free but no 25 KiB block. A fixed
                 * 8 KiB cache reservation must fail before any token overrun;
                 * it cannot allocate a full wire copy or worst-case output. */
                if (capacity - w < 2) return false;
                out[flag] |= 1u << bit;
                unsigned token = ((unsigned)(distance - 1) << 4) | (unsigned)(best - 3);
                out[w++] = token & 255;
                out[w++] = token >> 8;
                i += best;
            } else {
                if (w >= capacity) return false;
                out[w++] = src[i++];
            }
        }
    }
    *result = w;
    return true;
}

uint8_t *HQ_Pack(const void *input, size_t n, size_t *result)
{
    if (!result) return NULL;
    *result = 0;
    if (!input || n > LIMIT) return NULL;
    size_t capacity = n + n / 8 + 16;
    uint8_t *out = malloc(capacity);
    if (!out) return NULL;
    if (!HQ_PackInto(input, n, out, capacity, result)) {
        free(out);
        return NULL;
    }
    return out;
}
char *HQ_Unpack(const void *input, size_t n, size_t *result)
{
    const uint8_t *src=input;
    if (!src || !result || n<6 || src[0]!='H' || src[1]!='Q' || src[2]!=1 || src[3]) return NULL;
    size_t wanted=src[4]|((unsigned)src[5]<<8);
    if (wanted>LIMIT) return NULL;
    char *out=malloc(wanted+1);
    if (!out) return NULL;
    size_t r=6, w=0;
    while (w<wanted && r<n) {
        unsigned flags=src[r++];
        for (unsigned bit=0; bit<8 && w<wanted; ++bit) {
            if (flags & (1u<<bit)) {
                if (r+2>n) goto invalid;
                unsigned token=src[r]|((unsigned)src[r+1]<<8); r+=2;
                size_t distance=(token>>4)+1, count=(token&15)+3;
                if (distance>w || count>wanted-w) goto invalid;
                while (count--) {out[w]=out[w-distance]; ++w;}
            } else {
                if (r>=n) goto invalid;
                out[w++]=src[r++];
            }
        }
    }
    if (w!=wanted || r!=n) goto invalid;
    out[w]=0; *result=w; return out;
invalid:
    free(out); return NULL;
}
