#include "homehq.h"
#include "homehq_png.h"
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
static unsigned cache_invalidations, network_opens, requested;
static bool cancel_on_read, chunked, incomplete_http;
static int64_t advertised_length;
static uint8_t *source_png;
static size_t source_length;
struct mock_http {size_t offset;};
static struct mock_http connection;

const cJSON *cJSON_GetObjectItemCaseSensitive(const cJSON *object, const char *key)
{
    for (const cJSON *node = object ? object->child : NULL; node; node = node->next)
        if (!strcmp(node->string, key)) return node;
    return NULL;
}
bool cJSON_IsString(const cJSON *value) {return value && value->valuestring;}
void lv_img_cache_invalidate_src(const void *source) {(void)source; cache_invalidations++;}
int64_t esp_timer_get_time(void) {return 1000000;}
bool HQ_ServicePhotoRequest(const char *path)
{
    requested++;
    return !strncmp(path, home, 36) && path[36] == '/';
}
esp_err_t esp_crt_bundle_attach(void *configuration) {(void)configuration; return ESP_OK;}
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *configuration)
{
    assert(configuration->crt_bundle_attach == esp_crt_bundle_attach);
    assert(configuration->disable_auto_redirect);
    assert(!configuration->keep_alive_enable);
    assert(configuration->timeout_ms <= 15000);
    assert(configuration->buffer_size <= 2048);
    network_opens++;
    connection.offset = 0;
    return &connection;
}
esp_err_t esp_http_client_set_header(esp_http_client_handle_t client, const char *key, const char *value)
{
    (void)client;
    assert((!strcmp(key, "Authorization") && !strcmp(value, "Bearer transient-token")) ||
           (!strcmp(key, "apikey") && !strcmp(value, "public-key")));
    return ESP_OK;
}
esp_err_t esp_http_client_open(esp_http_client_handle_t client, int length)
{(void)client; assert(length == 0); return ESP_OK;}
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t client)
{(void)client; return advertised_length ? advertised_length : (chunked ? 0 : (int64_t)source_length);}
int esp_http_client_get_status_code(esp_http_client_handle_t client) {(void)client; return 200;}
int esp_http_client_read(esp_http_client_handle_t client, char *bytes, int length)
{
    if (cancel_on_read) {
        cancel_on_read = false;
        HQ_PhotoReset();
    }
    size_t count = source_length - client->offset;
    if (count > (size_t)length) count = length;
    memcpy(bytes, source_png + client->offset, count);
    client->offset += count;
    return count;
}
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t client)
{return !incomplete_http && client->offset == source_length;}
esp_err_t esp_http_client_close(esp_http_client_handle_t client) {(void)client; return ESP_OK;}
esp_err_t esp_http_client_cleanup(esp_http_client_handle_t client) {(void)client; return ESP_OK;}

static bool download(const char *url)
{return HQ_PhotoDownload(url, "transient-token", "public-key");}

int main(int argc, char **argv)
{
    assert(argc == 2);
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
    assert(HQ_Photo(&photo) == &homehq_photo_lake);
    HQ_PhotoMaintain(&photo);
    assert(requested == 1);
    assert(!download("http://invalid.invalid/anything"));
    snprintf(url, sizeof(url), "https://project.supabase.co/storage/v1/object/authenticated/homehq-photos/%s", second);
    assert(!download(url));
    assert(network_opens == 0);
    snprintf(url, sizeof(url), "https://project.supabase.co/storage/v1/object/authenticated/homehq-photos/%s", first);
    assert(download(url));
    assert(HQ_Photo(&photo) == &homehq_photo_lake); /* worker never mutates the UI image */
    assert(!download(url)); /* mailbox occupied: at most two display allocations */
    HQ_PhotoMaintain(&photo);
    const lv_img_dsc_t *active = HQ_Photo(&photo);
    assert(active != &homehq_photo_lake && active->data);
    assert(active->header.w == 128 && active->header.h == 72 && active->data_size == 18432);
    assert(HQ_PhotoChanged() && !HQ_PhotoChanged());

    path.valuestring = second;
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
    HQ_PhotoReset();
    HQ_PhotoMaintain(NULL);
    free(source_png);
    puts("photo mailbox: TLS/URL guards, adoption, cancellation, chunked and incomplete HTTP passed");
    return 0;
}
