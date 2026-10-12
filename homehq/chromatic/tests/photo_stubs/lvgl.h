#pragma once
#include <stdint.h>
typedef struct lv_obj_t lv_obj_t;
typedef struct {
    struct {unsigned cf, always_zero, w, h;} header;
    uint32_t data_size;
    const uint8_t *data;
} lv_img_dsc_t;
#define LV_IMG_CF_TRUE_COLOR 4
#define LV_COLOR_16_SWAP 0
void lv_img_cache_invalidate_src(const void *source);
