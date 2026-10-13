#include "homehq_photo_stage.h"
#include "esp_flash.h"
#include "esp_flash_encrypt.h"
#include "esp_partition.h"
#include "esp_rom_crc.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

#define STAGE_HEADER 64u
#define SECTOR_SIZE 4096u
static bool staged_claimed, writing, committed;
static size_t staged_length, erased_until;
static uint32_t staged_crc;
static HQ_PhotoStageGuard transaction_guard;
static void *transaction_context;

static uint32_t read32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static void write32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = value >> (8u * i);
}
static uint32_t header_crc(const uint8_t *header)
{
    uint32_t crc = esp_rom_crc32_le(0, header + 4, 12);
    return esp_rom_crc32_le(crc, header + 20, STAGE_HEADER - 20);
}
static bool header_valid(const uint8_t *header)
{
    if (memcmp(header, "HQPS", 4) || read32(header + 4) != 1 ||
        !read32(header + 8) || read32(header + 8) > HQ_PHOTO_STAGE_MAX ||
        read32(header + 16) != header_crc(header)) return false;
    for (size_t i = 20; i < STAGE_HEADER; ++i) if (header[i]) return false;
    return true;
}
static bool layout_safe(void)
{
    uint32_t bytes;
    if (esp_flash_encryption_enabled() || esp_flash_get_size(NULL, &bytes) != ESP_OK || bytes != 0x400000u)
        return false;
    unsigned found = 0, count = 0;
    esp_partition_iterator_t it = esp_partition_find(ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, NULL);
    while (it) {
        const esp_partition_t *p = esp_partition_get(it);
        ++count;
        if (p->address < HQ_PHOTO_STAGE_END && (uint64_t)p->address + p->size > HQ_PHOTO_STAGE_START) {
            esp_partition_iterator_release(it); return false;
        }
        if (p->type == ESP_PARTITION_TYPE_APP && p->subtype == ESP_PARTITION_SUBTYPE_APP_FACTORY &&
            p->address == 0x10000u && p->size == 0x100000u && !strcmp(p->label, "factory")) found |= 1;
        if (p->type == ESP_PARTITION_TYPE_DATA && p->subtype == ESP_PARTITION_SUBTYPE_DATA_NVS &&
            p->address == 0x9000u && p->size == 0x6000u && !strcmp(p->label, "nvs")) found |= 2;
        if (p->type == ESP_PARTITION_TYPE_DATA && p->subtype == ESP_PARTITION_SUBTYPE_DATA_PHY &&
            p->address == 0xf000u && p->size == 0x1000u && !strcmp(p->label, "phy_init")) found |= 4;
        it = esp_partition_next(it);
    }
    return found == 7 && count == 3;
}
static bool region_blank(void)
{
    uint8_t block[1024];
    for (uint32_t address = HQ_PHOTO_STAGE_START; address < HQ_PHOTO_STAGE_END; address += sizeof(block)) {
        if (esp_flash_read(NULL, block, address, sizeof(block)) != ESP_OK) return false;
        for (size_t i = 0; i < sizeof(block); ++i) if (block[i] != 255) return false;
    }
    return true;
}
static bool claim_region(void)
{
    if (!layout_safe()) return false;
    if (staged_claimed) return true;
    nvs_handle_t store;
    if (nvs_open("hqphotos", NVS_READWRITE, &store) != ESP_OK) return false;
    uint8_t value = 0;
    esp_err_t result = nvs_get_u8(store, "staged", &value);
    bool ok = result == ESP_OK ? value == 1 : result == ESP_ERR_NVS_NOT_FOUND;
    if (ok && !value) {
        uint8_t header[STAGE_HEADER];
        ok = (esp_flash_read(NULL, header, HQ_PHOTO_STAGE_START, sizeof(header)) == ESP_OK && header_valid(header)) ||
             region_blank();
        /* Before any erase, a durable own-region claim distinguishes our torn
         * first write from foreign data. Session clearing retains ownership. */
        if (ok) ok = nvs_set_u8(store, "staged", 1) == ESP_OK && nvs_commit(store) == ESP_OK;
    }
    nvs_close(store); staged_claimed = ok; return ok;
}
static bool current(HQ_PhotoStageGuard guard, void *context)
{
    bool valid = guard && guard == transaction_guard && context == transaction_context && guard(context);
    if (!valid) { writing = false; committed = false; }
    return valid;
}
bool HQ_PhotoStageBegin(HQ_PhotoStageGuard guard, void *context)
{
    writing = committed = false; staged_length = erased_until = 0; staged_crc = 0;
    transaction_guard = guard; transaction_context = context;
    if (!current(guard, context) || !claim_region() || !current(guard, context) ||
        esp_flash_erase_region(NULL, HQ_PHOTO_STAGE_START, SECTOR_SIZE) != ESP_OK) return false;
    vTaskDelay(1);
    writing = current(guard, context); return writing;
}
bool HQ_PhotoStageWrite(const void *bytes, size_t length, HQ_PhotoStageGuard guard, void *context)
{
    if (!writing || !current(guard, context) || (!bytes && length) || length > HQ_PHOTO_STAGE_MAX - staged_length) {
        writing = committed = false; return false;
    }
    const uint8_t *input = bytes;
    while (length) {
        if (!current(guard, context)) return false;
        if (staged_length == erased_until) {
            /* TLS and decoding never overlap. Erase only the next 4 KiB as
             * bytes arrive, yielding to input instead of pausing for 320 KiB. */
            if (esp_flash_erase_region(NULL, HQ_PHOTO_STAGE_PAYLOAD + erased_until, SECTOR_SIZE) != ESP_OK) {
                writing = false; return false;
            }
            erased_until += SECTOR_SIZE; vTaskDelay(1);
        }
        size_t count = erased_until - staged_length;
        if (count > length) count = length;
        if (!current(guard, context) || esp_flash_write(NULL, input, HQ_PHOTO_STAGE_PAYLOAD + staged_length, count) != ESP_OK) {
            writing = false; return false;
        }
        staged_crc = esp_rom_crc32_le(staged_crc, input, count);
        staged_length += count; input += count; length -= count;
    }
    return current(guard, context);
}
bool HQ_PhotoStageFinish(size_t *length, HQ_PhotoStageGuard guard, void *context)
{
    if (!length) return false;
    *length = 0;
    if (!writing || !staged_length || !current(guard, context)) return false;
    uint8_t block[1024]; uint32_t crc = 0;
    for (size_t offset = 0; offset < staged_length;) {
        size_t count = staged_length - offset;
        if (count > sizeof(block)) count = sizeof(block);
        if (!current(guard, context) || esp_flash_read(NULL, block, HQ_PHOTO_STAGE_PAYLOAD + offset, count) != ESP_OK)
            return false;
        crc = esp_rom_crc32_le(crc, block, count); offset += count;
    }
    if (crc != staged_crc) { writing = false; return false; }
    uint8_t header[STAGE_HEADER] = {0};
    memcpy(header, "HQPS", 4); write32(header + 4, 1); write32(header + 8, staged_length);
    write32(header + 12, staged_crc); write32(header + 16, header_crc(header));
    if (!current(guard, context) || esp_flash_write(NULL, header + 4, HQ_PHOTO_STAGE_START + 4, STAGE_HEADER - 4) != ESP_OK ||
        !current(guard, context) || esp_flash_write(NULL, header, HQ_PHOTO_STAGE_START, 4) != ESP_OK) return false;
    uint8_t verify[STAGE_HEADER];
    if (esp_flash_read(NULL, verify, HQ_PHOTO_STAGE_START, sizeof(verify)) != ESP_OK ||
        memcmp(header, verify, sizeof(header)) || !header_valid(verify) || !current(guard, context)) return false;
    committed = true; writing = false; *length = staged_length; return true;
}
bool HQ_PhotoStageRead(size_t offset, void *bytes, size_t length, HQ_PhotoStageGuard guard, void *context)
{
    if (!committed || !current(guard, context) || (!bytes && length) ||
        offset > staged_length || length > staged_length - offset) return false;
    if (!length) return true;
    return esp_flash_read(NULL, bytes, HQ_PHOTO_STAGE_PAYLOAD + offset, length) == ESP_OK && current(guard, context);
}
bool HQ_PhotoStageDrop(void)
{
    writing = committed = false; transaction_guard = NULL; transaction_context = NULL;
    if (!claim_region()) return false;
    const uint32_t invalid = 0; uint32_t check = UINT32_MAX;
    return esp_flash_write(NULL, &invalid, HQ_PHOTO_STAGE_START, sizeof(invalid)) == ESP_OK &&
           esp_flash_read(NULL, &check, HQ_PHOTO_STAGE_START, sizeof(check)) == ESP_OK && check == 0;
}
