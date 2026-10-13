/* Execute the pinned IDF header generator, not a model of its framing rules.
 * All token/key bytes here are synthetic; no network or identity is accessed. */
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "homehq_http.h"
#include "http_header.h"

static char *dummy(size_t length)
{
    char *value = malloc(length + 1); assert(value);
    memset(value, 'x', length); value[length] = 0; return value;
}
static bool terminated(size_t bearer_length, size_t key_length, unsigned width, bool photo_order)
{
    char *token = dummy(bearer_length), *key = dummy(key_length);
    char *authorization = malloc(bearer_length + 8); assert(authorization);
    snprintf(authorization, bearer_length + 8, "Bearer %s", token);
    http_header_handle_t header = http_header_init(); assert(header);
    assert(http_header_set(header, "Host", "test.supabase.invalid") == ESP_OK);
    assert(http_header_set(header, "User-Agent", "homehq-synthetic-check") == ESP_OK);
    if (photo_order) assert(http_header_set(header, "Authorization", authorization) == ESP_OK);
    assert(http_header_set(header, "apikey", key) == ESP_OK);
    if (!photo_order) assert(http_header_set(header, "Authorization", authorization) == ESP_OK);
    assert(http_header_set(header, "Content-Type", "application/json") == ESP_OK);
    char *chunk = malloc(width + 1), *output = calloc(1, bearer_length + key_length + 2048);
    assert(chunk && output);
    int index = 0; size_t used = 0; bool progress = true;
    for (unsigned turn = 0; turn < 20; ++turn) {
        /* request_send gives the first chunk less room for its request line,
         * then resets the width for each subsequent whole-header batch. */
        int count = (int)width - (turn ? 0 : 80);
        int next = http_header_generate_string(header, index, chunk, &count);
        if (!next) break;
        if (count <= 0 || next <= index) { progress = false; break; }
        memcpy(output + used, chunk, (size_t)count); used += (size_t)count;
        index = next;
    }
    bool complete = progress && used >= 4 && !memcmp(output + used - 4, "\r\n\r\n", 4) &&
        strstr(output, "Authorization: Bearer ") && strstr(output, "apikey: ");
    free(output); free(chunk); assert(http_header_destroy(header) == ESP_OK);
    free(authorization); free(key); free(token); return complete;
}
int main(void)
{
    /* At 512 bytes, the SDK permits exactly a 485-byte bearer line, then
     * silently stops progress at the next byte. A real device JWT was 970. */
    for (unsigned order = 0; order < 2; ++order) {
        assert(terminated(485, 16, 512, order));
        assert(!terminated(486, 16, 512, order));
        assert(!terminated(970, 244, 512, order));
        assert(!terminated(4096, 244, 1024, order));
        const size_t lengths[] = {970, 4096, 8192};
        for (unsigned i = 0; i < sizeof lengths / sizeof lengths[0]; ++i) {
            char *token = dummy(lengths[i]), *key = dummy(lengths[i]);
            unsigned width = HQ_HttpTxSize(token, key, 8192);
            assert(width && width <= 8224 && terminated(lengths[i], lengths[i], width, order));
            free(token); free(key);
        }
    }
    char *too_long = dummy(8193), *valid = dummy(970);
    assert(!HQ_HttpTxSize(too_long, valid, 8192));
    assert(!HQ_HttpTxSize(valid, too_long, 8192));
    assert(!HQ_HttpTxSize(NULL, valid, 8192));
    assert(!HQ_HttpTxSize(valid, valid, 8193));
    free(too_long); free(valid);
    puts("PASS pinned SDK whole-header boundaries: legacy stall reproduced; bounded JWT/key frames terminate");
    return 0;
}
