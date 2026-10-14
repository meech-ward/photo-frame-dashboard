#include "homehq.h"
#include "homehq_png.h"
#include "homehq_photo_cache.h"
#include "homehq_photo_stage.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char home[] = "12345678-1234-1234-1234-123456789abc";
static const uint8_t sample_pixel[] = {0, 0};
const lv_img_dsc_t homehq_photo_coast = {.data = sample_pixel};
const lv_img_dsc_t homehq_photo_lake = {.data = sample_pixel};
const lv_img_dsc_t homehq_photo_mountain = {.data = sample_pixel};
static unsigned cache_invalidations, network_opens, range_requests, requested;
static int64_t now_us = 1000000;
static bool cancel_on_read, leave_on_read, chunked, incomplete_http;
static bool service_current = true, account_change_on_read, http_active;
static bool storage_failure, cancel_on_cache_load, cancel_on_cache_save;
static bool cached;
static uint16_t cached_pixels[HQ_PHOTO_BYTES / sizeof(uint16_t)];
static char cached_path[106], cached_user[96];
static unsigned cache_saves, cache_loads;
unsigned photo_allocation_order, photo_destination_order, photo_decoder_order;
bool photo_fail_destination, photo_http_finished;
static uint8_t staged_bytes[HQ_PHOTO_STAGE_MAX];
static size_t staged_length;
static bool staged_writing, staged_complete, stage_write_failure, stage_finish_failure, stage_read_failure;
static struct {
    uint8_t before[32], pixels[32768], after[32];
} dictionary;
static int64_t advertised_length;
static int response_status = 206;
static const char *expected_bearer = "transient-token", *expected_apikey = "public-key";
static esp_err_t (*http_event)(esp_http_client_event_t *);
static void *http_event_context;
static bool receive_allocation_error, response_drained, break_reuse_once, retry_during_read;
static cJSON *displayed_photo;
static const char *connection_header;
static uint8_t *source_png;
static size_t source_length;
static const char *range_override, *encoding;
static bool missing_range, duplicate_range, changed_total, changed_etag, extra_body, short_body;
static unsigned fail_reads, stage_writes, completed_ranges, max_range_bytes;
static const char server_etag[] = "\"stable-photo\"";
struct mock_http {size_t offset, start, end; unsigned requests;};
static struct mock_http connection;

const cJSON *cJSON_GetObjectItemCaseSensitive(const cJSON *object, const char *key)
{
    for (const cJSON *node = object ? object->child : NULL; node; node = node->next)
        if (!strcmp(node->string, key)) return node;
    return NULL;
}
bool cJSON_IsString(const cJSON *value) {return value && value->valuestring;}
void lv_img_cache_invalidate_src(const void *source) {(void)source; cache_invalidations++;}
int64_t esp_timer_get_time(void) {return now_us;}
bool HQ_ServicePhotoRequest(const char *path)
{
    requested++;
    return !strncmp(path, home, 36) && path[36] == '/';
}
esp_err_t esp_crt_bundle_attach(void *configuration) {(void)configuration; return ESP_OK;}
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *configuration)
{
    assert(HQ_PhotoWorkerBusy());
    assert(configuration->crt_bundle_attach == esp_crt_bundle_attach);
    assert(configuration->disable_auto_redirect);
    assert(!configuration->keep_alive_enable);
    assert(configuration->timeout_ms <= 15000);
    assert(configuration->buffer_size <= 2048);
    assert(configuration->buffer_size_tx >= 1024 && configuration->buffer_size_tx <= 8224);
    assert((size_t)configuration->buffer_size_tx >= strlen(expected_bearer) + 32);
    assert((size_t)configuration->buffer_size_tx >= strlen(expected_apikey) + 16);
    http_event = configuration->event_handler; http_event_context = configuration->user_data;
    assert(!photo_destination_order && !photo_decoder_order && !photo_http_finished);
    network_opens++;
    http_active = true;
    connection.offset = connection.start = connection.end = 0; connection.requests = 0; response_drained = false;
    return &connection;
}
esp_err_t esp_http_client_set_header(esp_http_client_handle_t client, const char *key, const char *value)
{
    if (!strcmp(key, "Range")) {
        char extra;
        assert(sscanf(value, "bytes=%zu-%zu%c", &client->start, &client->end, &extra) == 2);
        assert(client->start < source_length && client->end >= client->start && client->end - client->start < 4096);
        if (client->end >= source_length) client->end = source_length - 1;
        client->offset = client->start;
    } else if (!strcmp(key, "Accept-Encoding")) {
        assert(!strcmp(value, "identity"));
    } else if (!strcmp(key, "If-Match")) {
        assert(!strcmp(value, server_etag));
    } else {
        assert((!strcmp(key, "Authorization") && !strncmp(value, "Bearer ", 7) && !strcmp(value + 7, expected_bearer)) ||
               (!strcmp(key, "apikey") && !strcmp(value, expected_apikey)));
    }
    return ESP_OK;
}
esp_err_t esp_http_client_open(esp_http_client_handle_t client, int length)
{
    assert(length == 0 && (!client->requests || response_drained));
    ++range_requests;
    ++client->requests;
    response_drained = false;
    if (break_reuse_once && client->requests > 1) { break_reuse_once = false; return -1; }
    return ESP_OK;
}
static void emit_header(const char *key, const char *value)
{
    esp_http_client_event_t event = {.event_id = HTTP_EVENT_ON_HEADER, .user_data = http_event_context,
                                    .header_key = key, .header_value = value};
    assert(http_event && http_event(&event) == ESP_OK);
}
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t client)
{
    if (receive_allocation_error) return -1;
    char range[80];
    snprintf(range, sizeof(range), "bytes %zu-%zu/%zu", client->start, client->end,
             source_length + (changed_total && client->start ? 1 : 0));
    if (!missing_range) emit_header("content-range", range_override ? range_override : range);
    if (duplicate_range) emit_header("Content-Range", range);
    emit_header("ETag", changed_etag && client->start ? "\"changed-photo\"" : server_etag);
    if (encoding) emit_header("Content-Encoding", encoding);
    if (connection_header) emit_header("Connection", connection_header);
    return advertised_length ? advertised_length : (chunked ? 0 : (int64_t)(client->end - client->start + 1));
}
int esp_http_client_get_status_code(esp_http_client_handle_t client) {(void)client; return response_status;}
int esp_http_client_read(esp_http_client_handle_t client, char *bytes, int length)
{
    assert(HQ_PhotoWorkerBusy());
    if (retry_during_read) {
        retry_during_read = false;
        unsigned before = requested;
        now_us += 31000000;
        HQ_PhotoMaintain(displayed_photo);
        assert(requested == before && HQ_PhotoWorkerBusy());
    }
    if (account_change_on_read) {
        account_change_on_read = false;
        service_current = false;
    }
    if (cancel_on_read) {
        cancel_on_read = false;
        HQ_PhotoReset();
        assert(HQ_PhotoWorkerBusy());
    }
    if (leave_on_read) {
        /* Simulate a GUI turn deleting its photo widgets during worker I/O. */
        leave_on_read = false;
        HQ_PhotoMaintain(NULL);
    }
    if (fail_reads) { --fail_reads; return -1; }
    size_t response_end = client->end + 1;
    if (short_body && response_end > client->start) --response_end;
    size_t count = client->offset < response_end ? response_end - client->offset : 0;
    if (!count && extra_body && client->offset == client->end + 1) {
        bytes[0] = 'x'; ++client->offset; return 1;
    }
    if (count > (size_t)length) count = length;
    if (!count && client->offset == client->end + 1) response_drained = true;
    memcpy(bytes, source_png + client->offset, count);
    client->offset += count;
    return count;
}
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t client)
{return !incomplete_http && client->offset == client->end + 1;}
int esp_tls_get_and_clear_last_error(void *handle, int *tls, int *flags)
{assert(handle == &receive_allocation_error && !flags); *tls = receive_allocation_error ? -32512 : 0; return receive_allocation_error ? 32774 : 0;}
esp_err_t esp_http_client_close(esp_http_client_handle_t client)
{
    (void)client;
    esp_http_client_event_t event = {.event_id = HTTP_EVENT_DISCONNECTED,
        .data = &receive_allocation_error, .user_data = http_event_context};
    assert(http_event && http_event(&event) == ESP_OK);
    return ESP_OK;
}
esp_err_t esp_http_client_cleanup(esp_http_client_handle_t client)
{(void)client; http_active = false; return ESP_OK;}

bool HQ_PhotoStageBegin(HQ_PhotoStageGuard guard, void *context)
{
    staged_length = 0; staged_complete = false; stage_writes = max_range_bytes = 0;
    staged_writing = guard(context); return staged_writing;
}
bool HQ_PhotoStageWrite(const void *bytes, size_t length, HQ_PhotoStageGuard guard, void *context)
{
    assert(HQ_PhotoWorkerBusy());
    assert((!http_active || response_drained) && !photo_destination_order && !photo_decoder_order);
    if (!staged_writing || stage_write_failure || !guard(context) || length > sizeof(staged_bytes) - staged_length)
        return false;
    assert(length <= 4096);
    if (length > max_range_bytes) max_range_bytes = (unsigned)length;
    ++stage_writes;
    memcpy(staged_bytes + staged_length, bytes, length); staged_length += length; return guard(context);
}
bool HQ_PhotoStageFinish(size_t *length, HQ_PhotoStageGuard guard, void *context)
{
    assert(!http_active && !photo_destination_order && !photo_decoder_order);
    *length = 0;
    if (!staged_writing || !staged_length || stage_finish_failure || !guard(context)) return false;
    assert(staged_length == source_length && !memcmp(staged_bytes, source_png, source_length));
    *length = staged_length; staged_complete = true; staged_writing = false; photo_http_finished = true; completed_ranges = stage_writes; return true;
}
bool HQ_PhotoStageRead(size_t offset, void *bytes, size_t length, HQ_PhotoStageGuard guard, void *context)
{
    assert(HQ_PhotoWorkerBusy());
    assert(!http_active && photo_http_finished && photo_destination_order && photo_decoder_order > photo_destination_order);
    if (!staged_complete || stage_read_failure || !guard(context) || offset > staged_length || length > staged_length - offset)
        return false;
    memcpy(bytes, staged_bytes + offset, length); return guard(context);
}
bool HQ_PhotoStageDrop(void)
{assert(!http_active); staged_writing = staged_complete = false; return true;}

bool HQ_PhotoCacheLoad(const char *user, const char *path, uint16_t *pixels,
                      HQ_PhotoCacheGuard guard, void *context)
{
    assert(!http_active);
    assert(HQ_PhotoWorkerBusy());
    cache_loads++;
    if (!guard(context) || !cached || strcmp(user, cached_user) || strcmp(path, cached_path)) return false;
    memcpy(pixels, cached_pixels, sizeof(cached_pixels));
    if (cancel_on_cache_load) { cancel_on_cache_load = false; HQ_PhotoReset(); }
    return guard(context);
}
bool HQ_PhotoCacheSave(const char *user, const char *path, const uint16_t *pixels,
                      HQ_PhotoCacheGuard guard, void *context)
{
    assert(!http_active); /* TLS cleanup precedes flash work and ownership transfer. */
    assert(HQ_PhotoWorkerBusy());
    cache_saves++;
    if (cancel_on_cache_save) { cancel_on_cache_save = false; service_current = false; }
    if (!guard(context) || storage_failure) return false;
    memcpy(cached_pixels, pixels, sizeof(cached_pixels));
    snprintf(cached_path, sizeof(cached_path), "%s", path);
    snprintf(cached_user, sizeof(cached_user), "%s", user);
    cached = true;
    return true;
}
bool HQ_PhotoCacheDrop(void)
{
    assert(!http_active);
    if (storage_failure) return false;
    cached = false;
    return true;
}

static bool account_current(void *context)
{assert(context == &service_current); return service_current;}

static bool download(const char *url)
{
    assert(!HQ_PhotoWorkerBusy());
    photo_allocation_order = photo_destination_order = photo_decoder_order = 0;
    photo_http_finished = false;
    bool result = HQ_PhotoDownload(url, "transient-token", "public-key", "member-a", account_current,
                                  &service_current, dictionary.pixels, sizeof(dictionary.pixels));
    assert(!HQ_PhotoWorkerBusy() && !http_active);
    for (unsigned i = 0; i < sizeof(dictionary.before); ++i)
        assert(dictionary.before[i] == 0xa5 && dictionary.after[i] == 0xa5);
    return result;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    memset(&dictionary, 0xa5, sizeof(dictionary));
    FILE *file = fopen(argv[1], "rb");
    assert(file);
    assert(!fseek(file, 0, SEEK_END));
    source_length = ftell(file);
    assert(!fseek(file, 0, SEEK_SET));
    source_png = malloc(source_length);
    assert(source_png && fread(source_png, 1, source_length, file) == source_length);
    fclose(file);

    char first[106], second[106], url[256];
    snprintf(first, sizeof(first), "%s/%064x.png", home, 1);
    snprintf(second, sizeof(second), "%s/%064x.png", home, 2);
    cJSON asset = {.string = "asset", .valuestring = "assets/photo-lake.png"};
    cJSON path = {.string = "path", .valuestring = first, .next = &asset};
    cJSON photo = {.child = &path};
    displayed_photo = &photo;
    assert(HQ_Photo(&photo) == &homehq_photo_lake);
    assert(HQ_PhotoIsFallback(&photo));
    HQ_PhotoMaintain(&photo);
    assert(requested == 1);
    assert(!download("http://invalid.invalid/anything"));
    snprintf(url, sizeof(url), "https://project.supabase.co/storage/v1/object/authenticated/homehq-photos/%s", second);
    assert(!download(url));
    assert(network_opens == 0);
    snprintf(url, sizeof(url), "https://project.supabase.co/storage/v1/object/authenticated/homehq-photos/%s", first);
    assert(!HQ_PhotoDownload(url, "transient-token", "public-key", "member-a", account_current,
                            &service_current, NULL, 0));
    assert(!HQ_PhotoDownload(url, "transient-token", "public-key", "member-a", account_current,
                            &service_current, dictionary.pixels, sizeof(dictionary.pixels) - 1));
    HQ_PhotoDiagnosticsInfo invalid_buffer;
    HQ_PhotoDiagnostics(&invalid_buffer);
    assert(invalid_buffer.stage == 2 && network_opens == 0);
    retry_during_read = true;
    photo_fail_destination = true;
    assert(!download(url) && network_opens == 1 && range_requests == (source_length + 4095) / 4096 && photo_http_finished);
    assert(completed_ranges == (source_length + 4095) / 4096 && max_range_bytes <= 4096);
    photo_fail_destination = false;
    HQ_PhotoDiagnostics(&invalid_buffer);
    assert(invalid_buffer.stage == 7);
    assert(download(url));
    assert(HQ_Photo(&photo) == &homehq_photo_lake); /* worker never mutates the UI image */
    unsigned before_ready = network_opens, before_ready_loads = cache_loads, before_ready_allocations = photo_allocation_order;
    assert(HQ_PhotoRestore("member-a", first, account_current, &service_current));
    assert(network_opens == before_ready && cache_loads == before_ready_loads && photo_allocation_order == before_ready_allocations);
    assert(!download(url)); /* mailbox occupied: at most two display allocations */
    HQ_PhotoMaintain(&photo);
    const lv_img_dsc_t *active = HQ_Photo(&photo);
    assert(active != &homehq_photo_lake && active->data);
    assert(active->header.w == 128 && active->header.h == 72 && active->data_size == 18432);
    assert(HQ_PhotoChanged() && !HQ_PhotoChanged());
    assert(!HQ_PhotoIsFallback(&photo));
    unsigned before_complete_request = requested;
    now_us += 31000000;
    HQ_PhotoMaintain(&photo);
    assert(requested == before_complete_request);
    before_ready_allocations = photo_allocation_order;
    before_ready_loads = cache_loads;
    assert(HQ_PhotoRestore("member-a", first, account_current, &service_current));
    assert(photo_allocation_order == before_ready_allocations && cache_loads == before_ready_loads);

    path.valuestring = second;
    /* UI deletes the old widget before retiring a changed selected path. */
    HQ_PhotoRetireUnused(&photo);
    assert(!active->data && HQ_PhotoIsFallback(&photo));
    HQ_PhotoMaintain(&photo);
    assert(HQ_Photo(&photo) == &homehq_photo_lake); /* metadata cannot reuse another photo's pixels */
    snprintf(url, sizeof(url), "https://project.supabase.co/storage/v1/object/authenticated/homehq-photos/%s", second);
    cancel_on_read = true;
    assert(!download(url));
    HQ_PhotoMaintain(&photo);
    assert(HQ_Photo(&photo) == &homehq_photo_lake);
    assert(cache_invalidations == 1 && HQ_PhotoChanged());

    chunked = true;
    assert(download(url));
    HQ_PhotoMaintain(&photo);
    assert(HQ_Photo(&photo)->data_size == 18432);
    assert(HQ_PhotoChanged());
    HQ_PhotoReset();
    HQ_PhotoMaintain(&photo);
    incomplete_http = true;
    assert(!download(url));
    incomplete_http = false;
    advertised_length = source_length + 1;
    assert(!download(url));
    advertised_length = HQ_PHOTO_MAX_PNG + 1;
    assert(!download(url));
    HQ_PhotoMaintain(&photo);
    assert(HQ_Photo(&photo) == &homehq_photo_lake);
    advertised_length = 0;
    HQ_PhotoChanged();
    assert(download(url));
    HQ_PhotoMaintain(&photo);
    const lv_img_dsc_t *last_frame = HQ_Photo(&photo);
    assert(last_frame->data && HQ_PhotoChanged());
    unsigned before_leave = cache_invalidations;
    HQ_PhotoMaintain(NULL);
    assert(!last_frame->data && HQ_Photo(&photo) == &homehq_photo_lake);
    assert(cache_invalidations == before_leave + 1 && HQ_PhotoChanged());
    assert(!download(url));
    HQ_PhotoMaintain(&photo);
    leave_on_read = true;
    assert(!download(url));
    assert(HQ_Photo(&photo) == &homehq_photo_lake);
    HQ_PhotoMaintain(&photo);
    assert(download(url));
    HQ_PhotoRetireUnused(&photo); /* Does not cancel matching pending pixels. */
    HQ_PhotoMaintain(NULL); /* A pending result is freed, never adopted on exit. */
    assert(HQ_Photo(&photo) == &homehq_photo_lake && !download(url));
    HQ_PhotoReset();
    HQ_PhotoMaintain(NULL);
    HQ_PhotoMaintain(&photo);
    unsigned before_restore = network_opens;
    assert(HQ_PhotoRestore("member-a", second, account_current, &service_current));
    assert(network_opens == before_restore && HQ_PhotoIsFallback(&photo));
    HQ_PhotoMaintain(&photo);
    assert(!HQ_PhotoIsFallback(&photo));
    const uint16_t *restored = (const uint16_t *)HQ_Photo(&photo)->data;
    for (unsigned i = 0; i < HQ_PHOTO_BYTES / sizeof(uint16_t); ++i) {
#if LV_COLOR_16_SWAP
        assert(restored[i] == (uint16_t)((cached_pixels[i] >> 8) | (cached_pixels[i] << 8)));
#else
        assert(restored[i] == cached_pixels[i]);
#endif
    }
    /* Departure cancels workers immediately but preserves the displayed frame
     * across failed hydration until the GUI deletes its widgets. */
    const lv_img_dsc_t *retained = HQ_Photo(&photo);
    HQ_PhotoReset(); assert(retained->data);
    HQ_PhotoMaintain(NULL); assert(!retained->data);
    HQ_PhotoMaintain(&photo);
    assert(!HQ_PhotoRestore("member-b", second, account_current, &service_current));
    cancel_on_cache_load = true;
    assert(!HQ_PhotoRestore("member-a", second, account_current, &service_current));
    HQ_PhotoMaintain(&photo);
    account_change_on_read = true;
    assert(!download(url));
    assert(HQ_PhotoIsFallback(&photo));
    service_current = true;
    storage_failure = true;
    assert(download(url)); /* Cache failure does not discard a verified RAM frame. */
    HQ_PhotoMaintain(&photo); assert(!HQ_PhotoIsFallback(&photo));
    assert(!HQ_PhotoClearCache());
    HQ_PhotoReset(); HQ_PhotoMaintain(NULL); HQ_PhotoMaintain(&photo);
    storage_failure = false; cancel_on_cache_save = true;
    assert(!download(url) && HQ_PhotoIsFallback(&photo));
    service_current = true;
    assert(HQ_PhotoClearCache());
    assert(!HQ_PhotoRestore("member-a", second, account_current, &service_current));
    HQ_PhotoDiagnosticsInfo stats;
    HQ_PhotoDiagnostics(&stats);
    assert(stats.download_ok && stats.download_failed && stats.cache_hits == 1 && stats.cache_misses >= 3);
    assert(stats.cache_saved && stats.cache_save_failed >= 2 && stats.cache_clear_failed == 1);
    assert(stats.http_status == 206 && stats.stage == 12 && cache_saves && cache_loads);
    unsigned prior_saves = cache_saves;
    unsigned before_retry = network_opens;
    fail_reads = 1;
    assert(download(url));
    assert(network_opens - before_retry == 2);
    HQ_PhotoReset(); HQ_PhotoMaintain(NULL); HQ_PhotoMaintain(&photo);
    before_retry = network_opens; fail_reads = 2;
    assert(!download(url) && network_opens == before_retry + 2 && !stage_writes && cache_saves == prior_saves + 1);
    prior_saves = cache_saves;
    if (source_length > 4096) {
        before_retry = network_opens;
        break_reuse_once = true;
        assert(download(url) && !break_reuse_once && network_opens == before_retry + 2);
        HQ_PhotoReset(); HQ_PhotoMaintain(NULL); HQ_PhotoMaintain(&photo);
        prior_saves = cache_saves;
    }
    before_retry = network_opens;
    connection_header = "keep-alive, CLOSE";
    assert(download(url) && network_opens - before_retry == (source_length + 4095) / 4096);
    connection_header = NULL;
    HQ_PhotoReset(); HQ_PhotoMaintain(NULL); HQ_PhotoMaintain(&photo);
    prior_saves = cache_saves;
    const char *malformed[] = {"bytes 1-4095/327680", "bytes 0-4096/327680", "bytes 0-4095/327681", "bytes 0-4095/*", "bytes 0-4095/327680 trailing"};
    for (unsigned c = 0; c < sizeof(malformed) / sizeof(malformed[0]); ++c) {
        range_override = malformed[c];
        assert(!download(url) && !stage_writes && cache_saves == prior_saves);
    }
    range_override = NULL;
    missing_range = true; assert(!download(url) && !stage_writes); missing_range = false;
    duplicate_range = true; assert(!download(url) && !stage_writes); duplicate_range = false;
    encoding = "gzip"; assert(!download(url) && !stage_writes); encoding = NULL;
    extra_body = true; assert(!download(url) && !stage_writes); extra_body = false;
    short_body = true; assert(!download(url) && !stage_writes); short_body = false;
    if (source_length > 4096) {
        changed_total = true; assert(!download(url) && stage_writes == 1); changed_total = false;
        changed_etag = true; assert(!download(url) && stage_writes == 1); changed_etag = false;
    }
    response_status = 200;
    assert(!download(url) && !stage_writes && cache_saves == prior_saves);
    response_status = 403;
    assert(!download(url) && cache_saves == prior_saves);
    HQ_PhotoDiagnostics(&stats);
    assert(stats.stage == 6 && stats.http_status == 403 && !http_active);
    response_status = 0; receive_allocation_error = true;
    assert(!download(url)); HQ_PhotoDiagnostics(&stats);
    assert(stats.stage == 6 && stats.http_status == 0 && stats.tls_error == -32512 && stats.transport_error == 32774);
    receive_allocation_error = false;
    response_status = 206;
    char large[8193];
    const size_t lengths[] = {970, 4096, 8192};
    for (unsigned c = 0; c < sizeof(lengths) / sizeof(lengths[0]); ++c) {
        memset(large, 'x', lengths[c]); large[lengths[c]] = 0;
        expected_bearer = expected_apikey = large;
        HQ_PhotoReset(); HQ_PhotoMaintain(NULL); HQ_PhotoMaintain(&photo);
        photo_allocation_order = photo_destination_order = photo_decoder_order = 0;
        photo_http_finished = false;
        assert(HQ_PhotoDownload(url, large, large, "member-a", account_current,
                               &service_current, dictionary.pixels, sizeof(dictionary.pixels)));
        HQ_PhotoMaintain(&photo);
    }
    expected_bearer = "transient-token"; expected_apikey = "public-key";
    HQ_PhotoReset(); HQ_PhotoMaintain(NULL); HQ_PhotoMaintain(&photo);
    prior_saves = cache_saves;
    stage_write_failure = true; assert(!download(url)); stage_write_failure = false;
    HQ_PhotoDiagnostics(&stats); assert(stats.stage == 14 && cache_saves == prior_saves);
    stage_finish_failure = true; assert(!download(url)); stage_finish_failure = false;
    HQ_PhotoDiagnostics(&stats); assert(stats.stage == 15 && cache_saves == prior_saves);
    stage_read_failure = true; assert(!download(url)); stage_read_failure = false;
    HQ_PhotoDiagnostics(&stats); assert(stats.stage == 16 && cache_saves == prior_saves);
    HQ_PhotoReset(); HQ_PhotoMaintain(NULL);
    free(source_png);
    puts("photo mailbox: reused ranges, reconnects, completed epochs, byte identity, cleanup, cancellation and malformed responses passed");
    return 0;
}
