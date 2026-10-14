#pragma once
#include <stdint.h>
typedef struct { uint32_t address, size; int type, subtype; char label[17]; } esp_partition_t;
typedef struct mock_iterator *esp_partition_iterator_t;
#define ESP_PARTITION_TYPE_ANY 255
#define ESP_PARTITION_SUBTYPE_ANY 255
#define ESP_PARTITION_TYPE_APP 0
#define ESP_PARTITION_SUBTYPE_APP_FACTORY 0
#define ESP_PARTITION_TYPE_DATA 1
#define ESP_PARTITION_SUBTYPE_DATA_NVS 2
#define ESP_PARTITION_SUBTYPE_DATA_PHY 1
esp_partition_iterator_t esp_partition_find(int, int, const char *);
const esp_partition_t *esp_partition_get(esp_partition_iterator_t);
esp_partition_iterator_t esp_partition_next(esp_partition_iterator_t);
void esp_partition_iterator_release(esp_partition_iterator_t);
