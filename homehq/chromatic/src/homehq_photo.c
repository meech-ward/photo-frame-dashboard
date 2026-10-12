#include "homehq.h"
#include "homehq_png.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <ctype.h>
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

extern const lv_img_dsc_t homehq_photo_coast;
extern const lv_img_dsc_t homehq_photo_lake;
extern const lv_img_dsc_t homehq_photo_mountain;

/* One worker decodes into an 18 KiB allocation while LVGL retains the previous
 * 18 KiB frame. Only the LVGL task changes its descriptor or releases its image;
 * workers transfer ownership through this mailbox after verified completion. */
static portMUX_TYPE photo_mutex = portMUX_INITIALIZER_UNLOCKED;
static uint16_t *pending_pixels;
static char pending_path[106];
static char requested_path[106];
static unsigned photo_epoch;
static bool reset_pending;
static uint16_t *active_pixels;
static char active_path[106];
static bool changed;
static int64_t retry_at;
static lv_img_dsc_t active_image = {
    .header = {.cf = LV_IMG_CF_TRUE_COLOR, .always_zero = 0,
               .w = HQ_PHOTO_WIDTH, .h = HQ_PHOTO_HEIGHT},
    .data_size = HQ_PHOTO_BYTES
};

static const char *field(const cJSON *object, const char *key)
{
    const cJSON *value = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(value) ? value->valuestring : NULL;
}

static bool path_valid(const char *path)
{
    /* The uploader uses <household UUID>/<SHA-256>.png. These exact characters
     * need no URL escaping and cannot change the authenticated Storage route. */
    if (!path || strlen(path) != 105 || path[36] != '/' ||
        strcmp(path + 101, ".png")) return false;
    for (unsigned i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (path[i] != '-') return false;
        } else if (!isxdigit((unsigned char)path[i])) return false;
    }
    for (unsigned i = 37; i < 101; i++)
        if (!isxdigit((unsigned char)path[i])) return false;
    return true;
}

static const char *url_path(const char *url)
{
    static const char route[] = "/storage/v1/object/authenticated/homehq-photos/";
    if (!url || strncmp(url, "https://", 8)) return NULL;
    const char *slash = strchr(url + 8, '/');
    if (!slash || slash == url + 8 || slash - url > 261 ||
        strncmp(slash, route, sizeof(route) - 1)) return NULL;
    for (const char *p = url + 8; p < slash; p++)
        if (!isalnum((unsigned char)*p) && *p != '-' && *p != '.') return NULL;
    const char *path = slash + sizeof(route) - 1;
    return path_valid(path) ? path : NULL;
}

static void release_active(void)
{
    if (!active_pixels) return;
    /* The descriptor address is stable across downloads. Invalidate LVGL's
     * source cache before changing its data pointer so a prior decoded source
     * cannot outlive the pixel allocation. This runs only on the LVGL task. */
    lv_img_cache_invalidate_src(&active_image);
    free(active_pixels);
    active_pixels = NULL;
    active_image.data = NULL;
    active_path[0] = 0;
    changed = true;
}

const lv_img_dsc_t *HQ_Photo(const cJSON *photo)
{
    const char *path = field(photo, "path");
    if (active_pixels && path && !strcmp(path, active_path)) return &active_image;
    const char *asset = field(photo, "asset");
    if (asset && !strcmp(asset, "assets/photo-lake.png")) return &homehq_photo_lake;
    if (asset && !strcmp(asset, "assets/photo-mountain.png")) return &homehq_photo_mountain;
    return &homehq_photo_coast;
}

void HQ_PhotoMaintain(const cJSON *photo)
{
    const char *path = field(photo, "path");
    if (!path_valid(path)) path = "";
    uint16_t *incoming;
    char incoming_path[sizeof(pending_path)];
    bool reset;
    portENTER_CRITICAL(&photo_mutex);
    incoming = pending_pixels;
    pending_pixels = NULL;
    memcpy(incoming_path, pending_path, sizeof(incoming_path));
    reset = reset_pending;
    reset_pending = false;
    bool different = strcmp(path, requested_path) != 0;
    if (different) {
        memcpy(requested_path, path, strlen(path) + 1);
        photo_epoch++;
    }
    portEXIT_CRITICAL(&photo_mutex);
    if (reset) release_active();
    if (incoming && !reset && !strcmp(path, incoming_path)) {
        release_active();
        active_pixels = incoming;
        memcpy(active_path, incoming_path, sizeof(active_path));
        active_image.data = (const uint8_t *)active_pixels;
        changed = true;
        incoming = NULL;
    }
    free(incoming);
    int64_t now = esp_timer_get_time() / 1000;
    if (!path[0] || (active_pixels && !strcmp(path, active_path))) return;
    if (different || now >= retry_at) {
        /* Retry failures without blocking a button handler. The service owns
         * credentials, home-membership validation and its network work queue. */
        retry_at = now + (HQ_ServicePhotoRequest(path) ? 30000 : 2000);
    }
}

bool HQ_PhotoChanged(void)
{
    bool result = changed;
    changed = false;
    return result;
}

void HQ_PhotoReset(void)
{
    /* Logout can race a TLS read. Its epoch cancels publication, and the LVGL
     * task releases the displayed private pixels at its next maintain call. */
    portENTER_CRITICAL(&photo_mutex);
    photo_epoch++;
    requested_path[0] = 0;
    reset_pending = true;
    uint16_t *old_pending = pending_pixels;
    pending_pixels = NULL;
    portEXIT_CRITICAL(&photo_mutex);
    free(old_pending);
}

bool HQ_PhotoDownload(const char *url, const char *bearer, const char *apikey)
{
    const char *path = url_path(url);
    if (!path || !bearer || !bearer[0] || !apikey || !apikey[0] ||
        strlen(bearer) > 8192 || strlen(apikey) > 8192) return false;
    portENTER_CRITICAL(&photo_mutex);
    unsigned epoch = photo_epoch;
    bool wanted = !pending_pixels && !strcmp(path, requested_path);
    portEXIT_CRITICAL(&photo_mutex);
    if (!wanted) return false;

    uint16_t *pixels = malloc(HQ_PHOTO_BYTES);
    HQ_PngStream *stream = HQ_PngNew(pixels);
    char *authorization = calloc(1, strlen(bearer) + 8);
    esp_http_client_handle_t client = NULL;
    bool success = false;
    if (!pixels || !stream || !authorization) goto cleanup;
    snprintf(authorization, strlen(bearer) + 8, "Bearer %s", bearer);
    esp_http_client_config_t config = {
        .url = url,
        .timeout_ms = 15000,
        .buffer_size = 2048,
        .buffer_size_tx = 512,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .disable_auto_redirect = true,
        .keep_alive_enable = false
    };
    client = esp_http_client_init(&config);
    if (!client || esp_http_client_set_header(client, "Authorization", authorization) != ESP_OK ||
        esp_http_client_set_header(client, "apikey", apikey) != ESP_OK ||
        esp_http_client_open(client, 0) != ESP_OK) goto cleanup;
    int64_t length = esp_http_client_fetch_headers(client);
    if (length < 0 || length > HQ_PHOTO_MAX_PNG ||
        esp_http_client_get_status_code(client) != 200) goto cleanup;
    uint8_t input[1024];
    size_t received = 0;
    for (;;) {
        portENTER_CRITICAL(&photo_mutex);
        wanted = epoch == photo_epoch && !strcmp(path, requested_path);
        portEXIT_CRITICAL(&photo_mutex);
        if (!wanted) goto cleanup;
        int count = esp_http_client_read(client, (char *)input, sizeof(input));
        if (count < 0) goto cleanup;
        if (!count) break;
        received += count;
        if (received > HQ_PHOTO_MAX_PNG || !HQ_PngFeed(stream, input, count)) goto cleanup;
    }
    if ((length > 0 && received != (size_t)length) ||
        !esp_http_client_is_complete_data_received(client) || !HQ_PngComplete(stream)) goto cleanup;
#if LV_COLOR_16_SWAP
    for (unsigned i = 0; i < HQ_PHOTO_WIDTH * HQ_PHOTO_HEIGHT; i++)
        pixels[i] = (pixels[i] >> 8) | (pixels[i] << 8);
#endif
    portENTER_CRITICAL(&photo_mutex);
    wanted = epoch == photo_epoch && !strcmp(path, requested_path);
    uint16_t *old_pending = NULL;
    if (wanted) {
        old_pending = pending_pixels;
        pending_pixels = pixels;
        memcpy(pending_path, path, strlen(path) + 1);
        pixels = NULL;
        success = true;
    }
    portEXIT_CRITICAL(&photo_mutex);
    free(old_pending);
cleanup:
    if (client) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
    }
    if (authorization) memset(authorization, 0, strlen(authorization));
    free(authorization);
    HQ_PngDestroy(stream);
    free(pixels);
    return success;
}
