#pragma once
#include <stddef.h>
#include <string.h>

static inline unsigned HQ_HttpTxSize(const char *token, const char *key, size_t maximum)
{
    if (!token || !key || maximum > 8192) return 0;
    size_t bearer_length = strlen(token), key_length = strlen(key);
    if (bearer_length > maximum || key_length > maximum) return 0;
    /* IDF 5.3 emits whole header lines. A physical 970-byte ordinary JWT
     * creates a 994-byte Authorization line: a 512-byte TX buffer silently
     * left the request unterminated while open() still reported success. */
    size_t width = 1024;
    if (width < bearer_length + 32) width = bearer_length + 32;
    if (width < key_length + 16) width = key_length + 16;
    return (unsigned)width;
}
