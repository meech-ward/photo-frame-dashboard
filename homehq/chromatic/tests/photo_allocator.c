#undef malloc
#undef calloc
#undef free
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>

extern unsigned photo_allocation_order, photo_destination_order, photo_decoder_order;
extern bool photo_fail_destination;
extern bool photo_http_finished;

static bool allocation(size_t bytes)
{
    unsigned order = ++photo_allocation_order;
    if (!photo_http_finished) return true;
    if (bytes == 18432) {
        photo_destination_order = order;
        if (photo_fail_destination) return false;
    } else if (bytes >= 8192 && bytes < 18432 && !photo_decoder_order) {
        photo_decoder_order = order;
    }
    return true;
}

void *HQ_TestPhotoMalloc(size_t bytes)
{ return allocation(bytes) ? malloc(bytes) : NULL; }
void *HQ_TestPhotoCalloc(size_t count, size_t bytes)
{ return allocation(count * bytes) ? calloc(count, bytes) : NULL; }
void HQ_TestPhotoFree(void *pointer) { free(pointer); }
