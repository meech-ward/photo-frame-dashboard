/* Flash and NVS are isolated mocks. Including the actual helper allows this
 * host harness to reset only volatile transaction state across a simulated
 * cold boot while preserving the NOR image and committed ownership flag. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "../src/homehq_photo_stage.c"

static uint8_t flash[0x400000], payload[HQ_PHOTO_STAGE_MAX], output[HQ_PHOTO_STAGE_MAX];
static uint32_t chip_size = sizeof(flash);
static bool encrypted, size_fault, flag_exists, staged_exists, all_reads_fail;
static uint8_t flag_value, staged_value;
static int nvs_fault, writes, erases, reads, fail_write, fail_erase, fail_read, silent_write;
static size_t partial;
static unsigned yields, current_generation, guard_calls, cancel_guard, cancel_yield, cancel_read;
static uint32_t write_address[256], write_length[256];
typedef struct { unsigned generation; } Context;
static Context owner, other;
static esp_partition_t partitions[4];
static unsigned partition_count;
struct mock_iterator { unsigned index; };
static struct mock_iterator iterator;
static bool iterator_active;

static void bounds(uint32_t address, uint32_t length)
{
    assert(address >= HQ_PHOTO_STAGE_START && address <= HQ_PHOTO_STAGE_END);
    assert(length <= HQ_PHOTO_STAGE_END - address);
}
esp_err_t esp_flash_get_size(esp_flash_t *chip, uint32_t *size)
{ assert(!chip); if (size_fault) return ESP_FAIL; *size = chip_size; return ESP_OK; }
bool esp_flash_encryption_enabled(void) { return encrypted; }
esp_err_t esp_flash_read(esp_flash_t *chip, void *bytes, uint32_t address, uint32_t length)
{
    assert(!chip); bounds(address, length); ++reads;
    if (all_reads_fail || reads == fail_read) return ESP_FAIL;
    if (length) memcpy(bytes, flash + address, length);
    if ((unsigned)reads == cancel_read) ++current_generation;
    return ESP_OK;
}
esp_err_t esp_flash_write(esp_flash_t *chip, const void *input, uint32_t address, uint32_t length)
{
    assert(!chip); bounds(address, length); assert(writes < 256);
    write_address[writes] = address; write_length[writes] = length; ++writes;
    if (writes == silent_write) return ESP_OK;
    bool fail = writes == fail_write;
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
    assert(!chip); bounds(address, length); assert(!(address % 4096) && length == 4096);
    bool fail = ++erases == fail_erase;
    memset(flash + address, 255, fail && partial < length ? partial : length);
    return fail ? ESP_FAIL : ESP_OK;
}
uint32_t esp_rom_crc32_le(uint32_t crc, const uint8_t *bytes, uint32_t length)
{
    crc = ~crc;
    for (uint32_t i = 0; i < length; ++i) {
        crc ^= bytes[i];
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
    assert(handle == 1 && !strcmp(name, "staged"));
    if (nvs_fault == 2) return ESP_FAIL;
    if (!flag_exists) return ESP_ERR_NVS_NOT_FOUND;
    *value = flag_value; return ESP_OK;
}
esp_err_t nvs_set_u8(nvs_handle_t handle, const char *name, uint8_t value)
{
    assert(handle == 1 && !strcmp(name, "staged") && value == 1);
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
void vTaskDelay(TickType_t ticks)
{
    assert(ticks == 1); ++yields;
    if (yields == cancel_yield) ++current_generation;
}
static bool current_owner(void *opaque)
{
    Context *context = opaque; assert(context == &owner || context == &other);
    if (++guard_calls == cancel_guard) ++current_generation;
    return context->generation == current_generation;
}
static bool alternate_guard(void *opaque) { return current_owner(opaque); }
static void reboot(void)
{
    staged_claimed = writing = committed = false;
    staged_length = erased_until = 0; staged_crc = 0;
    transaction_guard = NULL; transaction_context = NULL;
    nvs_fault = writes = erases = reads = fail_write = fail_erase = fail_read = silent_write = 0;
    partial = 0; all_reads_fail = false;
    yields = guard_calls = cancel_guard = cancel_yield = cancel_read = 0;
    current_generation = owner.generation = other.generation = 1;
    assert(!iterator_active);
}
static void fresh(void)
{
    reboot(); memset(flash, 0x55, sizeof(flash));
    memset(flash + HQ_PHOTO_STAGE_START, 255, HQ_PHOTO_STAGE_END - HQ_PHOTO_STAGE_START);
    encrypted = size_fault = flag_exists = staged_exists = false; flag_value = staged_value = 0;
    chip_size = sizeof(flash);
    partitions[0] = (esp_partition_t){.address=0x9000,.size=0x6000,.type=1,.subtype=2,.label="nvs"};
    partitions[1] = (esp_partition_t){.address=0xf000,.size=0x1000,.type=1,.subtype=1,.label="phy_init"};
    partitions[2] = (esp_partition_t){.address=0x10000,.size=0x100000,.type=0,.subtype=0,.label="factory"};
    partition_count = 3;
}
static void canaries(void)
{
    assert(!iterator_active);
    for (uint32_t i = 0; i < HQ_PHOTO_STAGE_START; ++i) assert(flash[i] == 0x55);
    for (uint32_t i = HQ_PHOTO_STAGE_END; i < sizeof(flash); ++i) assert(flash[i] == 0x55);
}
static bool begin(void) { return HQ_PhotoStageBegin(current_owner, &owner); }
static bool write_bytes(const void *bytes, size_t length)
{ return HQ_PhotoStageWrite(bytes, length, current_owner, &owner); }
static bool finish(size_t *length) { return HQ_PhotoStageFinish(length, current_owner, &owner); }
static bool read_bytes(size_t offset, void *bytes, size_t length)
{ return HQ_PhotoStageRead(offset, bytes, length, current_owner, &owner); }
static void stage(size_t length)
{
    assert(begin() && write_bytes(payload, length)); size_t written = 0;
    assert(finish(&written) && written == length);
}

static void ownership(void)
{
    fresh(); assert(!HQ_PhotoStageBegin(NULL, &owner) && !erases && !writes); canaries();
    for (unsigned change = 0; change < 7; ++change) {
        fresh();
        if (change == 0) encrypted = true;
        if (change == 1) chip_size = 0x800000;
        if (change == 2) size_fault = true;
        if (change == 3) partitions[2].size = 0x200000;
        if (change == 4) partitions[2].label[0] = 'x';
        if (change == 5) partition_count = 4;
        if (change == 6) partitions[3] = (esp_partition_t){.address=HQ_PHOTO_STAGE_START,.size=4096,.type=1}, partition_count = 4;
        assert(!begin() && !erases && !writes); canaries();
    }
    for (uint32_t offset = 0; offset < HQ_PHOTO_STAGE_END - HQ_PHOTO_STAGE_START; offset += 4096) {
        fresh(); flash[HQ_PHOTO_STAGE_START + offset] = 0;
        assert(!begin() && !HQ_PhotoStageDrop() && !erases && !writes && !flag_exists); canaries();
    }
    for (int fault = 1; fault <= 4; ++fault) {
        fresh(); nvs_fault = fault;
        assert(!begin() && !erases && !writes && !flag_exists); canaries();
    }
    fresh(); all_reads_fail = true; assert(!begin() && !erases && !writes && !flag_exists);
    fresh(); flag_exists = true; flag_value = 2; assert(!begin() && !erases && !writes);
    fresh(); fail_erase = 1; partial = 17; assert(!begin() && flag_exists && flag_value == 1);
    flash[HQ_PHOTO_STAGE_PAYLOAD] = 0; reboot(); assert(begin()); canaries();
}
static void transactions(void)
{
    fresh(); assert(!read_bytes(0, output, 1) && !write_bytes(payload, 1));
    assert(begin() && erases == 1 && yields == 1 && flag_exists);
    assert(write_bytes(NULL, 0)); size_t length = 99; assert(!finish(&length) && !length);
    assert(write_bytes(payload, 4095) && erases == 2 && yields == 2);
    assert(!read_bytes(0, output, 1));
    assert(write_bytes(payload + 4095, 3) && erases == 3 && yields == 3);
    assert(finish(&length) && length == 4098);
    assert(write_address[writes - 2] == HQ_PHOTO_STAGE_START + 4 && write_length[writes - 2] == 60);
    assert(write_address[writes - 1] == HQ_PHOTO_STAGE_START && write_length[writes - 1] == 4);
    assert(read_bytes(0, output, length) && !memcmp(output, payload, length));
    assert(read_bytes(length, output, 0) && !read_bytes(length, output, 1));
    assert(!read_bytes(SIZE_MAX, output, 1) && !read_bytes(0, NULL, 1));
    assert(!write_bytes(payload, 1)); canaries();
    fresh(); stage(HQ_PHOTO_STAGE_MAX); assert(erases == 81 && yields == 81);
    assert(read_bytes(0, output, sizeof(output)) && !memcmp(output, payload, sizeof(output))); canaries();
    assert(begin() && write_bytes(payload + 100, 13)); assert(finish(&length) && length == 13);
    assert(read_bytes(0, output, 13) && !memcmp(output, payload + 100, 13));
    assert(!read_bytes(13, output, 1)); canaries();
    reboot(); assert(!read_bytes(0, output, 1)); assert(begin());
    assert(!read_bytes(0, output, 1)); canaries();
    fresh(); assert(begin()); assert(!write_bytes(payload, SIZE_MAX)); assert(!finish(&length));
    fresh(); assert(begin()); assert(!write_bytes(NULL, 1)); assert(!finish(&length));
    fresh(); assert(begin()); assert(!finish(NULL)); assert(!read_bytes(0, output, 1)); canaries();
}
static void failures(void)
{
    size_t length;
    fresh(); assert(begin()); fail_erase = erases + 1; partial = 31;
    assert(!write_bytes(payload, 32) && !finish(&length) && !read_bytes(0, output, 1)); canaries();
    fresh(); assert(begin()); fail_write = writes + 1; partial = 17;
    assert(!write_bytes(payload, 32) && !finish(&length) && !read_bytes(0, output, 1)); canaries();
    fresh(); assert(begin()); silent_write = writes + 1; assert(write_bytes(payload, 32));
    assert(!finish(&length) && !read_bytes(0, output, 1)); canaries();
    fresh(); assert(begin() && write_bytes(payload, 32)); flash[HQ_PHOTO_STAGE_PAYLOAD + 7] ^= 1;
    assert(!finish(&length) && !read_bytes(0, output, 1)); canaries();
    for (unsigned failing_write = 1; failing_write <= 2; ++failing_write) {
        fresh(); assert(begin() && write_bytes(payload, 32)); fail_write = writes + failing_write; partial = 2;
        assert(!finish(&length) && !length && !read_bytes(0, output, 1));
        reboot(); assert(!read_bytes(0, output, 1)); assert(begin()); canaries();
    }
    for (unsigned skipped_write = 1; skipped_write <= 2; ++skipped_write) {
        fresh(); assert(begin() && write_bytes(payload, 32)); silent_write = writes + skipped_write;
        assert(!finish(&length) && !length && !read_bytes(0, output, 1)); canaries();
    }
    fresh(); assert(begin() && write_bytes(payload, 32)); fail_read = reads + 2;
    assert(!finish(&length) && !read_bytes(0, output, 1));
    reboot(); assert(!read_bytes(0, output, 1)); assert(begin()); canaries();
    fresh(); assert(begin() && write_bytes(payload, 32)); fail_read = reads + 1;
    assert(!finish(&length) && !read_bytes(0, output, 1)); fail_read = 0;
    assert(finish(&length) && length == 32);
    fail_read = reads + 1; assert(!read_bytes(0, output, 32)); fail_read = 0;
    assert(read_bytes(0, output, 32));
    silent_write = writes + 1; assert(!HQ_PhotoStageDrop() && !read_bytes(0, output, 1));
    silent_write = 0; assert(HQ_PhotoStageDrop() && !memcmp(flash + HQ_PHOTO_STAGE_START, "\0\0\0\0", 4)); canaries();
    fresh(); stage(32); fail_read = reads + 1;
    assert(!HQ_PhotoStageDrop() && !read_bytes(0, output, 1));
    fail_read = 0; assert(HQ_PhotoStageDrop()); canaries();
    fresh(); stage(32); flag_exists = false; reboot(); assert(begin()); canaries();
    fresh(); stage(32); flash[HQ_PHOTO_STAGE_START + 16] ^= 1; flag_exists = false; reboot();
    assert(!begin() && !erases && !writes); canaries();
}
static void cancellation(void)
{
    size_t length;
    fresh(); ++current_generation; assert(!begin() && !erases && !writes);
    fresh(); assert(begin()); assert(!HQ_PhotoStageWrite(payload, 1, current_owner, &other));
    assert(!finish(&length)); canaries();
    fresh(); assert(begin()); assert(!HQ_PhotoStageWrite(payload, 1, alternate_guard, &owner));
    assert(!finish(&length)); canaries();
    fresh(); assert(begin()); cancel_yield = yields + 1;
    assert(!write_bytes(payload, 5000) && !writes && !finish(&length)); canaries();
    fresh(); assert(begin() && write_bytes(payload, 2048)); cancel_read = reads + 1;
    assert(!finish(&length) && !read_bytes(0, output, 1)); canaries();
    fresh(); stage(32); ++current_generation;
    assert(!read_bytes(0, output, 32)); owner.generation = current_generation;
    assert(!read_bytes(0, output, 32)); assert(begin() && write_bytes(payload, 16) && finish(&length)); canaries();
    fresh(); stage(32); assert(HQ_PhotoStageDrop()); assert(!read_bytes(0, output, 1));
    assert(flag_exists && flag_value == 1); reboot(); assert(begin()); canaries();
}
int main(void)
{
    for (size_t i = 0; i < sizeof(payload); ++i) payload[i] = (uint8_t)(i * 71u + i / 97u);
    ownership(); transactions(); failures(); cancellation();
    puts("photo staging: flash/NVS ownership, bounds, lazy yields, commit/CRC, faults, restart and cancellation passed");
    return 0;
}
