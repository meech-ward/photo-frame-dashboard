#pragma once
#include <stdint.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NVS_NOT_FOUND -2
typedef struct esp_flash_t esp_flash_t;
esp_err_t esp_flash_get_size(esp_flash_t *, uint32_t *);
esp_err_t esp_flash_read(esp_flash_t *, void *, uint32_t, uint32_t);
esp_err_t esp_flash_write(esp_flash_t *, const void *, uint32_t, uint32_t);
esp_err_t esp_flash_erase_region(esp_flash_t *, uint32_t, uint32_t);
