#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
/* Include the production module so only this host harness can reset its
 * volatile claim, simulating a cold boot with persistent flash/NVS unchanged. */
#include "../src/homehq_photo_cache.c"

static uint8_t flash[0x400000], baseline[2 * SLOT_SIZE];
static uint32_t chip_size = sizeof(flash);
static bool encrypted, flag_exists, staged_exists;
static uint8_t flag_value, staged_value;
static int nvs_fault, writes, erases, reads, fail_write, fail_erase, fail_read, silent_write;
static size_t partial;
static int guard_calls, cancel_guard;
static esp_partition_t partitions[4];
static unsigned partition_count;
struct mock_iterator { unsigned index; };
static struct mock_iterator iterator;
static bool iterator_active;

static void bounds(uint32_t address, uint32_t length)
{
    assert(address >= CACHE_START && address <= CACHE_END && length <= CACHE_END - address);
}

esp_err_t esp_flash_get_size(esp_flash_t *chip, uint32_t *size)
{ assert(!chip); *size = chip_size; return ESP_OK; }
bool esp_flash_encryption_enabled(void) { return encrypted; }
esp_err_t esp_flash_read(esp_flash_t *chip, void *output, uint32_t address, uint32_t length)
{
    assert(!chip); bounds(address, length);
    if (++reads == fail_read) return ESP_FAIL;
    memcpy(output, flash + address, length); return ESP_OK;
}
esp_err_t esp_flash_write(esp_flash_t *chip, const void *input, uint32_t address, uint32_t length)
{
    assert(!chip); bounds(address, length);
    bool fail = ++writes == fail_write;
    if (writes == silent_write) return ESP_OK;
    size_t count = fail && partial < length ? partial : length;
    const uint8_t *bytes = input;
    for (size_t i = 0; i < count; ++i) {
        assert((flash[address + i] & bytes[i]) == bytes[i]);
        flash[address + i] &= bytes[i];
    }
    return fail ? ESP_FAIL : ESP_OK;
}
esp_err_t esp_flash_erase_region(esp_flash_t *chip, uint32_t address, uint32_t length)
{
    assert(!chip); bounds(address, length); assert(!(address % 4096) && !(length % 4096));
    bool fail = ++erases == fail_erase;
    memset(flash + address, 255, fail && partial < length ? partial : length);
    return fail ? ESP_FAIL : ESP_OK;
}
uint32_t esp_rom_crc32_le(uint32_t crc, const uint8_t *data, uint32_t length)
{
    crc = ~crc;
    for (uint32_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    return ~crc;
}
esp_partition_iterator_t esp_partition_find(int type, int subtype, const char *label)
{
    assert(type == 255 && subtype == 255 && !label && !iterator_active);
    iterator.index = 0; iterator_active = partition_count != 0;
    return iterator_active ? &iterator : NULL;
}
const esp_partition_t *esp_partition_get(esp_partition_iterator_t it)
{ assert(it == &iterator && iterator_active); return &partitions[it->index]; }
esp_partition_iterator_t esp_partition_next(esp_partition_iterator_t it)
{
    assert(it == &iterator && iterator_active);
    iterator_active = ++it->index < partition_count;
    return iterator_active ? it : NULL;
}
void esp_partition_iterator_release(esp_partition_iterator_t it)
{ assert(it == &iterator && iterator_active); iterator_active = false; }
esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle)
{
    assert(!strcmp(name, "hqphotos") && mode == NVS_READWRITE);
    if (nvs_fault == 1) return ESP_FAIL;
    *handle = 1; staged_exists = flag_exists; staged_value = flag_value; return ESP_OK;
}
esp_err_t nvs_get_u8(nvs_handle_t handle, const char *name, uint8_t *value)
{
    assert(handle == 1 && !strcmp(name, "claimed"));
    if (nvs_fault == 2) return ESP_FAIL;
    if (!flag_exists) return ESP_ERR_NVS_NOT_FOUND;
    *value = flag_value; return ESP_OK;
}
esp_err_t nvs_set_u8(nvs_handle_t handle, const char *name, uint8_t value)
{
    assert(handle == 1 && !strcmp(name, "claimed") && value == 1);
    if (nvs_fault == 3) return ESP_FAIL;
    staged_exists = true; staged_value = value; return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t handle)
{
    assert(handle == 1);
    if (nvs_fault == 4) return ESP_FAIL;
    flag_exists = staged_exists; flag_value = staged_value; return ESP_OK;
}
void nvs_close(nvs_handle_t handle) { assert(handle == 1); }

static bool current(void *context)
{
    assert(context == &guard_calls);
    return ++guard_calls != cancel_guard;
}
static void reboot(void)
{
    claimed = false; writes = erases = reads = fail_write = fail_erase = fail_read = nvs_fault = 0;
    silent_write = 0;
    guard_calls = cancel_guard = 0; partial = 0; assert(!iterator_active);
}
static void fresh(void)
{
    reboot(); memset(flash, 0x55, sizeof(flash)); memset(flash + CACHE_START, 255, 2 * SLOT_SIZE);
    chip_size = sizeof(flash); encrypted = false; flag_exists = false; flag_value = 0;
    partitions[0] = (esp_partition_t){.address=0x9000,.size=0x6000,.type=1,.subtype=2,.label="nvs"};
    partitions[1] = (esp_partition_t){.address=0xf000,.size=0x1000,.type=1,.subtype=1,.label="phy_init"};
    partitions[2] = (esp_partition_t){.address=0x10000,.size=0x100000,.type=0,.subtype=0,.label="factory"};
    partition_count = 3;
}
static char paths[4][106];
static uint16_t pixels[4][HQ_PHOTO_CACHE_BYTES / 2], loaded[HQ_PHOTO_CACHE_BYTES / 2];
static bool save(unsigned image)
{ return HQ_PhotoCacheSave("member-a", paths[image], pixels[image], current, &guard_calls); }
static bool load(unsigned image)
{
    if (!HQ_PhotoCacheLoad("member-a", paths[image], loaded, current, &guard_calls)) return false;
    assert(!memcmp(loaded, pixels[image], sizeof(loaded))); return true;
}
static void outside_unchanged(void)
{
    for (size_t i = 0; i < CACHE_START; ++i) assert(flash[i] == 0x55);
    for (size_t i = CACHE_END; i < sizeof(flash); ++i) assert(flash[i] == 0x55);
}
static void restore(void)
{ memcpy(flash + CACHE_START, baseline, sizeof(baseline)); reboot(); }

int main(void)
{
    for (unsigned image = 0; image < 4; ++image) {
        memcpy(paths[image], "12345678-1234-1234-1234-123456789abc/", 37);
        memset(paths[image] + 37, 'a' + image, 64); memcpy(paths[image] + 101, ".png", 5);
        for (unsigned i = 0; i < HQ_PHOTO_CACHE_BYTES / 2; ++i) pixels[image][i] = i * 71u + image;
    }
    fresh(); assert(!load(0) && writes == 0 && erases == 0 && flag_exists);
    assert(save(0) && save(1)); reboot(); assert(load(0) && load(1));
    int previous_writes = writes;
    assert(!HQ_PhotoCacheLoad("member-b", paths[0], loaded, current, &guard_calls));
    assert(writes == previous_writes);
    assert(save(2)); assert(!load(0) && load(1) && load(2));
    assert(HQ_PhotoCacheDrop()); reboot(); assert(!load(1) && !load(2)); assert(save(3) && load(3));
    outside_unchanged();

    /* Cold first-use refuses foreign data in either slot, including a valid
     * looking magic with an invalid header CRC. No erase/claim is permitted. */
    for (unsigned slot = 0; slot < 2; ++slot) {
        fresh(); flash[CACHE_START + slot * SLOT_SIZE + 4096] = 0;
        assert(!save(0) && !HQ_PhotoCacheDrop() && !flag_exists && writes == 0 && erases == 0);
    }
    fresh(); memcpy(flash + CACHE_START, "HQC1", 4);
    assert(!save(0) && !flag_exists && !writes && !erases);
    for (int fault = 1; fault <= 4; ++fault) {
        fresh(); nvs_fault = fault; assert(!save(0) && !writes && !erases);
    }
    fresh(); flag_exists = true; flag_value = 2; assert(!save(0) && !writes && !erases);
    fresh(); assert(save(0)); flag_exists = false; reboot(); assert(load(0) && flag_exists && !writes && !erases);

    for (unsigned mode = 0; mode < 6; ++mode) {
        fresh();
        if (mode == 0) chip_size /= 2;
        if (mode == 1) encrypted = true;
        if (mode == 2) partitions[2].size += 4096;
        if (mode == 3) partitions[0].size = 4096;
        if (mode == 4) partitions[2].label[0] = 'x';
        if (mode == 5) {
            partitions[3] = (esp_partition_t){.address=CACHE_START,.size=4096,.type=1,.subtype=0,.label="foreign"};
            partition_count = 4;
        }
        assert(!save(0) && !HQ_PhotoCacheDrop() && !writes && !erases && !iterator_active);
    }
    fresh(); assert(save(0)); chip_size /= 2; assert(!load(0));

    fresh(); assert(save(0) && save(1)); memcpy(baseline, flash + CACHE_START, sizeof(baseline));
    const size_t cuts[] = {0, 1, 2, 3, 128, 251, 252, 4096, HQ_PHOTO_CACHE_BYTES - 1, HQ_PHOTO_CACHE_BYTES, SLOT_SIZE};
    for (unsigned stage = 0; stage < 4; ++stage) for (unsigned cut = 0; cut < sizeof(cuts) / sizeof(cuts[0]); ++cut) {
        restore(); partial = cuts[cut];
        if (!stage) fail_erase = 1; else fail_write = stage;
        assert(!save(2)); reboot(); assert(load(1));
        bool committed = load(2);
        assert(committed == (stage == 3 && cuts[cut] >= 4));
        outside_unchanged();
    }
    for (int gate = 1; gate <= 6; ++gate) {
        restore(); cancel_guard = gate; assert(!save(2)); reboot(); assert(load(1));
        assert(load(2) == (gate == 6));
        assert(!HQ_PhotoCacheLoad("member-b", paths[2], loaded, current, &guard_calls));
        assert(HQ_PhotoCacheDrop() && !load(2));
    }
    restore(); assert(!HQ_PhotoCacheLoad("member-a", paths[0], loaded, NULL, NULL));
    for (int gate = 1; gate <= 3; ++gate) {
        restore(); cancel_guard = gate; assert(!load(0));
    }
    for (int read = 1; read <= 2; ++read) {
        restore(); fail_read = read; assert(!load(0));
    }
    restore(); fail_read = 3; assert(!save(2)); reboot(); assert(load(1) && !load(2));
    for (int read = 1; read <= 2; ++read) {
        restore(); fail_read = read; assert(!save(2) && !writes && !erases);
    }
    for (int write = 1; write <= 3; ++write) {
        restore(); silent_write = write; assert(!save(2)); reboot(); assert(load(1) && !load(2));
    }
    restore(); flash[CACHE_START + HEADER_SIZE + 17] ^= 1; assert(!load(0) && load(1));
    const unsigned offsets[] = {4, 6, 8, 10, 12, 28, 30, 32, 128 + 36, 128 + 105, 255};
    for (unsigned c = 0; c < sizeof(offsets) / sizeof(offsets[0]); ++c) {
        restore(); uint8_t *header = flash + CACHE_START;
        header[offsets[c]] ^= 1; write32(header + 24, header_crc(header));
        assert(!load(0) && load(1));
    }
    restore(); flash[CACHE_START + 24] ^= 1; assert(!load(0));
    restore(); assert(!HQ_PhotoCacheSave("private@example.com", paths[0], pixels[0], current, &guard_calls));
    assert(!HQ_PhotoCacheSave("member-a", "../foreign.png", pixels[0], current, &guard_calls));
    assert(!HQ_PhotoCacheSave("member-a", paths[0], NULL, current, &guard_calls));
    assert(!HQ_PhotoCacheLoad("member-a", paths[0], NULL, current, &guard_calls));
    restore(); fail_write = 1; partial = 4; assert(!HQ_PhotoCacheDrop()); reboot(); assert(!load(0) && !load(1));
    restore(); silent_write = 1; assert(!HQ_PhotoCacheDrop()); reboot(); assert(load(0) && !load(1));
    puts("Photo cache: identity, cold boot, bounds, ownership, faults, torn writes and cancellation passed");
    return 0;
}
