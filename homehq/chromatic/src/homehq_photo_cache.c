#include "homehq_photo_cache.h"
#include "esp_flash.h"
#include "esp_flash_encrypt.h"
#include "esp_partition.h"
#include "esp_rom_crc.h"
#include "nvs.h"
#include <stddef.h>
#include <string.h>

/* The 4 MiB before-Home-HQ backup has 752 erased sectors after the factory
 * application's exclusive end. Only these ten sectors are app-owned data;
 * neither firmware deployment nor this module changes the partition table. */
#define CACHE_START 0x110000u
#define SLOT_SIZE 0x5000u
#define CACHE_END (CACHE_START + 2u * SLOT_SIZE)
#define HEADER_SIZE 256u
#define USER_OFFSET 32u
#define USER_CAPACITY 96u
#define PATH_OFFSET 128u
#define PATH_CAPACITY 106u
static bool claimed;

static uint16_t read16(const uint8_t *p)
{
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t read32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void write16(uint8_t *p, uint16_t value)
{
    p[0] = value;
    p[1] = value >> 8;
}

static void write32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = value >> (8u * i);
}

static bool hex(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
           (c >= 'A' && c <= 'F');
}

static bool path_valid(const char *path)
{
    if (!path || strlen(path) != 105 || path[36] != '/' || strcmp(path + 101, ".png")) return false;
    for (unsigned i = 0; i < 36; ++i) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (path[i] != '-') return false;
        } else if (!hex(path[i])) return false;
    }
    for (unsigned i = 37; i < 101; ++i) if (!hex(path[i])) return false;
    return true;
}

static bool user_valid(const char *user)
{
    if (!user) return false;
    size_t n = strlen(user);
    if (!n || n >= USER_CAPACITY) return false;
    for (size_t i = 0; i < n; ++i) {
        char c = user[i];
        if (!(c >= 'a' && c <= 'z') && !(c >= 'A' && c <= 'Z') &&
            !(c >= '0' && c <= '9') && c != '-' && c != '_' && c != '.') return false;
    }
    return true;
}

static uint32_t header_crc(const uint8_t *header)
{
    /* The final four-byte magic is the commit. A cut before it cannot turn
     * an erased/torn payload into an image, even if its body was written. */
    uint32_t crc = esp_rom_crc32_le(0, header + 4, 20);
    return esp_rom_crc32_le(crc, header + 28, HEADER_SIZE - 28);
}

static bool header_valid(const uint8_t *header)
{
    if (memcmp(header, "HQC1", 4) || read16(header + 4) != 1 ||
        read16(header + 6) != HQ_PHOTO_CACHE_WIDTH ||
        read16(header + 8) != HQ_PHOTO_CACHE_HEIGHT || read16(header + 10) != 1 ||
        read32(header + 12) != HQ_PHOTO_CACHE_BYTES ||
        read32(header + 24) != header_crc(header)) return false;
    size_t user_length = read16(header + 28);
    if (!user_length || user_length >= USER_CAPACITY || read16(header + 30) != 105 ||
        header[USER_OFFSET + user_length] || header[PATH_OFFSET + 105]) return false;
    if (!user_valid((const char *)header + USER_OFFSET) ||
        strlen((const char *)header + USER_OFFSET) != user_length ||
        !path_valid((const char *)header + PATH_OFFSET)) return false;
    for (size_t i = USER_OFFSET + user_length + 1; i < PATH_OFFSET; ++i)
        if (header[i]) return false;
    for (size_t i = PATH_OFFSET + PATH_CAPACITY; i < HEADER_SIZE; ++i)
        if (header[i]) return false;
    return true;
}

static bool layout_safe(void)
{
    uint32_t size;
    if (esp_flash_encryption_enabled() || esp_flash_get_size(NULL, &size) != ESP_OK || size != 0x400000u)
        return false;
    unsigned found = 0, count = 0;
    esp_partition_iterator_t it = esp_partition_find(ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, NULL);
    while (it) {
        const esp_partition_t *p = esp_partition_get(it);
        ++count;
        if (p->address < CACHE_END && (uint64_t)p->address + p->size > CACHE_START) {
            esp_partition_iterator_release(it);
            return false;
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

static bool slot_blank(unsigned slot)
{
    uint8_t block[256];
    for (uint32_t offset = 0; offset < SLOT_SIZE; offset += sizeof(block)) {
        if (esp_flash_read(NULL, block, CACHE_START + slot * SLOT_SIZE + offset, sizeof(block)) != ESP_OK)
            return false;
        for (size_t i = 0; i < sizeof(block); ++i) if (block[i] != 255) return false;
    }
    return true;
}

static bool claim_region(void)
{
    if (!layout_safe()) return false;
    if (claimed) return true;
    nvs_handle_t store;
    if (nvs_open("hqphotos", NVS_READWRITE, &store) != ESP_OK) return false;
    uint8_t value = 0;
    esp_err_t result = nvs_get_u8(store, "claimed", &value);
    bool ok = result == ESP_OK ? value == 1 : result == ESP_ERR_NVS_NOT_FOUND;
    if (ok && !value) {
        for (unsigned slot = 0; slot < 2 && ok; ++slot) {
            uint8_t header[HEADER_SIZE];
            ok = slot_blank(slot) ||
                 (esp_flash_read(NULL, header, CACHE_START + slot * SLOT_SIZE, sizeof(header)) == ESP_OK &&
                  header_valid(header));
        }
        /* This durable claim precedes the first erase. After a power cut with
         * no valid header, it distinguishes our interrupted write from unknown
         * pre-existing tail data. Identity clearing intentionally retains it. */
        if (ok) ok = nvs_set_u8(store, "claimed", 1) == ESP_OK && nvs_commit(store) == ESP_OK;
    }
    nvs_close(store);
    claimed = ok;
    return ok;
}

static bool read_header(unsigned slot, uint8_t *header)
{
    return esp_flash_read(NULL, header, CACHE_START + slot * SLOT_SIZE, HEADER_SIZE) == ESP_OK &&
           header_valid(header);
}

static bool verify_pixels(unsigned slot, uint32_t expected)
{
    uint8_t block[256];
    uint32_t crc = 0;
    for (uint32_t offset = 0; offset < HQ_PHOTO_CACHE_BYTES; offset += sizeof(block)) {
        if (esp_flash_read(NULL, block, CACHE_START + slot * SLOT_SIZE + HEADER_SIZE + offset,
                           sizeof(block)) != ESP_OK) return false;
        crc = esp_rom_crc32_le(crc, block, sizeof(block));
    }
    return crc == expected;
}

bool HQ_PhotoCacheLoad(const char *user, const char *path, uint16_t *pixels,
                      HQ_PhotoCacheGuard guard, void *context)
{
    if (!pixels || !guard || !guard(context) || !user_valid(user) || !path_valid(path) || !claim_region())
        return false;
    for (unsigned slot = 0; slot < 2; ++slot) {
        uint8_t header[HEADER_SIZE];
        if (!read_header(slot, header) || strcmp(user, (const char *)header + USER_OFFSET) ||
            strcmp(path, (const char *)header + PATH_OFFSET)) continue;
        if (!guard(context)) return false;
        if (esp_flash_read(NULL, pixels, CACHE_START + slot * SLOT_SIZE + HEADER_SIZE,
                           HQ_PHOTO_CACHE_BYTES) != ESP_OK) continue;
        if (!guard(context)) return false;
        if (esp_rom_crc32_le(0, (const uint8_t *)pixels, HQ_PHOTO_CACHE_BYTES) == read32(header + 20))
            return true;
    }
    return false;
}

bool HQ_PhotoCacheSave(const char *user, const char *path, const uint16_t *pixels,
                      HQ_PhotoCacheGuard guard, void *context)
{
    if (!pixels || !guard || !guard(context) || !user_valid(user) || !path_valid(path) || !claim_region())
        return false;
    uint8_t headers[2][HEADER_SIZE];
    /* An I/O error cannot nominate a supposedly empty eviction slot. Preserve
     * both prior images until their metadata was actually read successfully. */
    if (esp_flash_read(NULL, headers[0], CACHE_START, HEADER_SIZE) != ESP_OK ||
        esp_flash_read(NULL, headers[1], CACHE_START + SLOT_SIZE, HEADER_SIZE) != ESP_OK) return false;
    bool valid[2] = {header_valid(headers[0]), header_valid(headers[1])};
    /* Keep the other prior frame across replacement, just as the badge's two
     * slots do. A cache hit does not write sequence metadata or wear flash. */
    unsigned newest = valid[1] && (!valid[0] || (int32_t)(read32(headers[1] + 16) - read32(headers[0] + 16)) > 0);
    uint32_t sequence = valid[newest] ? read32(headers[newest] + 16) + 1 : 0;
    unsigned slot = !valid[0] ? 0 : !valid[1] ? 1 : 1 - newest;
    uint32_t address = CACHE_START + slot * SLOT_SIZE;
    uint32_t crc = esp_rom_crc32_le(0, (const uint8_t *)pixels, HQ_PHOTO_CACHE_BYTES);
    if (!guard(context) || esp_flash_erase_region(NULL, address, SLOT_SIZE) != ESP_OK ||
        !guard(context) || esp_flash_write(NULL, pixels, address + HEADER_SIZE, HQ_PHOTO_CACHE_BYTES) != ESP_OK ||
        !verify_pixels(slot, crc)) return false;
    uint8_t *header = headers[slot];
    memset(header, 0, HEADER_SIZE);
    memcpy(header, "HQC1", 4);
    write16(header + 4, 1);
    write16(header + 6, HQ_PHOTO_CACHE_WIDTH);
    write16(header + 8, HQ_PHOTO_CACHE_HEIGHT);
    write16(header + 10, 1);
    write32(header + 12, HQ_PHOTO_CACHE_BYTES);
    write32(header + 16, sequence);
    write32(header + 20, crc);
    write16(header + 28, strlen(user));
    write16(header + 30, 105);
    memcpy(header + USER_OFFSET, user, strlen(user) + 1);
    memcpy(header + PATH_OFFSET, path, PATH_CAPACITY);
    write32(header + 24, header_crc(header));
    if (!guard(context) || esp_flash_write(NULL, header + 4, address + 4, HEADER_SIZE - 4) != ESP_OK ||
        !guard(context) || esp_flash_write(NULL, header, address, 4) != ESP_OK) return false;
    uint8_t verify[HEADER_SIZE];
    return guard(context) && read_header(slot, verify) && !memcmp(header, verify, HEADER_SIZE);
}

bool HQ_PhotoCacheDrop(void)
{
    if (!claim_region()) return false;
    /* Invalidating both app-owned headers clears offline presentation without
     * erasing any firmware/configuration or exposing a prior identity's frame. */
    const uint32_t invalid = 0;
    bool first = esp_flash_write(NULL, &invalid, CACHE_START, sizeof(invalid)) == ESP_OK;
    bool second = esp_flash_write(NULL, &invalid, CACHE_START + SLOT_SIZE, sizeof(invalid)) == ESP_OK;
    uint32_t before = UINT32_MAX, after = UINT32_MAX;
    bool checked_first = esp_flash_read(NULL, &before, CACHE_START, sizeof(before)) == ESP_OK;
    bool checked_second = esp_flash_read(NULL, &after, CACHE_START + SLOT_SIZE, sizeof(after)) == ESP_OK;
    return first && second && checked_first && checked_second && before == 0 && after == 0;
}
