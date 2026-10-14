#include "homehq.h"
#include "homehq_png.h"
#include "homehq_photo_cache.h"
#include "homehq_photo_stage.h"
#include "homehq_photo_range.h"
#include "homehq_http.h"
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdio.h>
#include <ctype.h>
#include "esp_http_client.h"
#include "esp_tls.h"
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
static unsigned completed_epoch;
static bool epoch_completed;
static bool worker_busy;
static bool reset_pending;
static uint16_t *active_pixels;
static char active_path[106];
static bool changed;
static int64_t retry_at;
static HQ_PhotoDiagnosticsInfo photo_stats;
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

bool HQ_PhotoIsFallback(const cJSON *photo)
{
    const char *path = field(photo, "path");
    return !active_pixels || !path || strcmp(path, active_path) != 0;
}

void HQ_PhotoRetireUnused(const cJSON *photo)
{
    const char *path = field(photo, "path");
    /* Called only after deleting the prior image widget. Unlike NULL maintain,
     * this gives back its 18 KiB without canceling a matching pending result. */
    if (active_pixels && (!path || strcmp(path, active_path))) release_active();
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
    bool complete = epoch_completed && completed_epoch == photo_epoch;
    bool busy = worker_busy;
    portEXIT_CRITICAL(&photo_mutex);
    /* NULL means the displayed photo widgets have been deleted by LVGL. Give
     * their 18 KiB back before a larger page projection or its TLS work starts;
     * changing the requested epoch also cancels an in-flight old download. */
    if (reset || !photo) release_active();
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
    /* An accepted long transfer owns this request until cleanup. Polling its
     * 30-second retry timer must not enqueue a second same-path operation. */
    if (!path[0] || complete || (!different && busy) ||
        (active_pixels && !strcmp(path, active_path))) return;
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

bool HQ_PhotoWorkerBusy(void)
{
    portENTER_CRITICAL(&photo_mutex);
    bool busy = worker_busy;
    portEXIT_CRITICAL(&photo_mutex);
    return busy;
}

static void worker_finished(void)
{
    portENTER_CRITICAL(&photo_mutex);
    worker_busy = false;
    portEXIT_CRITICAL(&photo_mutex);
}

void HQ_PhotoDiagnostics(HQ_PhotoDiagnosticsInfo *result)
{
    if (!result) return;
    portENTER_CRITICAL(&photo_mutex);
    *result = photo_stats;
    portEXIT_CRITICAL(&photo_mutex);
}

bool HQ_PhotoClearCache(void)
{
    bool thumbnails = HQ_PhotoCacheDrop();
    bool staging = HQ_PhotoStageDrop();
    bool cleared = thumbnails && staging;
    portENTER_CRITICAL(&photo_mutex);
    if (!cleared) ++photo_stats.cache_clear_failed;
    portEXIT_CRITICAL(&photo_mutex);
    return cleared;
}

typedef struct { int tls, transport; } PhotoErrors;

typedef struct {
    PhotoErrors errors;
    bool invalid, range_seen, etag_seen, encoding_seen, connection_close;
    char range[80], etag[97];
} PhotoHeaders;

typedef struct {
    esp_http_client_handle_t client;
    PhotoHeaders headers;
} PhotoSession;

static bool header_token(const char *value, const char *token)
{
    size_t length = strlen(token);
    while (*value) {
        while (*value == ' ' || *value == '\t' || *value == ',') ++value;
        const char *end = strchr(value, ',');
        if (!end) end = value + strlen(value);
        const char *trimmed = end;
        while (trimmed > value && (trimmed[-1] == ' ' || trimmed[-1] == '\t')) --trimmed;
        if ((size_t)(trimmed - value) == length && !strncasecmp(value, token, length)) return true;
        value = *end ? end + 1 : end;
    }
    return false;
}

static void capture_header(PhotoHeaders *headers, const char *key, const char *value)
{
    if (!key || !value) { headers->invalid = true; return; }
    if (!strcasecmp(key, "Content-Range")) {
        size_t length = strlen(value);
        if (headers->range_seen || length >= sizeof(headers->range)) {
            headers->invalid = true;
            return;
        }
        headers->range_seen = true;
        memcpy(headers->range, value, length + 1);
    } else if (!strcasecmp(key, "ETag")) {
        size_t length = strlen(value);
        if (headers->etag_seen || length >= sizeof(headers->etag) || !HQ_PhotoETagValid(value)) {
            headers->invalid = true;
            return;
        }
        headers->etag_seen = true;
        memcpy(headers->etag, value, length + 1);
    } else if (!strcasecmp(key, "Content-Encoding")) {
        if (headers->encoding_seen || strcasecmp(value, "identity")) headers->invalid = true;
        headers->encoding_seen = true;
    } else if (!strcasecmp(key, "Connection") && header_token(value, "close")) {
        headers->connection_close = true;
    }
}

static esp_err_t photo_http_event(esp_http_client_event_t *event)
{
    if (event->event_id == HTTP_EVENT_ON_HEADER && event->user_data) {
        capture_header(event->user_data, event->header_key, event->header_value);
    }
    if ((event->event_id == HTTP_EVENT_ERROR || event->event_id == HTTP_EVENT_DISCONNECTED) &&
        event->data && event->user_data) {
        PhotoErrors *errors = &((PhotoHeaders *)event->user_data)->errors;
        int tls = 0;
        int transport = esp_tls_get_and_clear_last_error((esp_tls_error_handle_t)event->data, &tls, NULL);
        if (tls || transport) { errors->tls = tls; errors->transport = transport; }
    }
    return ESP_OK;
}

static void download_result(bool success, unsigned stage, unsigned http_status, const PhotoErrors *errors)
{
    portENTER_CRITICAL(&photo_mutex);
    if (success) ++photo_stats.download_ok;
    else ++photo_stats.download_failed;
    photo_stats.stage = success ? 0 : stage;
    photo_stats.http_status = http_status;
    photo_stats.tls_error = errors ? errors->tls : 0;
    photo_stats.transport_error = errors ? errors->transport : 0;
    portEXIT_CRITICAL(&photo_mutex);
}

void HQ_PhotoReset(void)
{
    /* Logout can race a TLS read. Its epoch cancels publication, and the LVGL
     * task releases the displayed private pixels at its next maintain call. */
    portENTER_CRITICAL(&photo_mutex);
    photo_epoch++;
    epoch_completed = false;
    requested_path[0] = 0;
    reset_pending = true;
    uint16_t *old_pending = pending_pixels;
    pending_pixels = NULL;
    portEXIT_CRITICAL(&photo_mutex);
    free(old_pending);
}

typedef struct {
    const char *path;
    unsigned epoch;
    HQ_PhotoGuard guard;
    void *context;
} PhotoRequest;

static bool request_current(void *context)
{
    const PhotoRequest *request = context;
    /* Account checks take the service guard first; do not hold the photo
     * critical section while calling it, because logout uses that order. */
    if (!request->guard(request->context)) return false;
    portENTER_CRITICAL(&photo_mutex);
    bool current = request->epoch == photo_epoch && !pending_pixels &&
                   !strcmp(request->path, requested_path);
    portEXIT_CRITICAL(&photo_mutex);
    return current;
}

static bool request_begin(PhotoRequest *request, const char *path,
                          HQ_PhotoGuard guard, void *context)
{
    if (!guard || !guard(context) || !path_valid(path)) return false;
    portENTER_CRITICAL(&photo_mutex);
    request->epoch = photo_epoch;
    bool current = !pending_pixels && !strcmp(path, requested_path) &&
                   !(epoch_completed && completed_epoch == photo_epoch);
    /* The GUI cancels then waits before allocating a larger page projection.
     * Set busy in this same epoch check so it cannot miss a just-starting job. */
    if (current) worker_busy = true;
    portEXIT_CRITICAL(&photo_mutex);
    request->path = path;
    request->guard = guard;
    request->context = context;
    return current;
}

static bool publish_pixels(PhotoRequest *request, uint16_t *pixels)
{
    if (!request_current(request)) return false;
#if LV_COLOR_16_SWAP
    for (unsigned i = 0; i < HQ_PHOTO_WIDTH * HQ_PHOTO_HEIGHT; i++)
        pixels[i] = (pixels[i] >> 8) | (pixels[i] << 8);
#endif
    if (!request->guard(request->context)) return false;
    portENTER_CRITICAL(&photo_mutex);
    bool current = request->epoch == photo_epoch && !pending_pixels &&
                   !strcmp(request->path, requested_path);
    if (current) {
        pending_pixels = pixels;
        memcpy(pending_path, request->path, sizeof(pending_path));
        completed_epoch = request->epoch;
        epoch_completed = true;
    }
    portEXIT_CRITICAL(&photo_mutex);
    return current;
}

bool HQ_PhotoRestore(const char *user, const char *path, HQ_PhotoGuard guard, void *context)
{
    if (!user || !*user || strlen(user) >= 96) return false;
    if (!guard || !guard(context) || !path_valid(path)) return false;
    portENTER_CRITICAL(&photo_mutex);
    bool ready = epoch_completed && completed_epoch == photo_epoch &&
                 !strcmp(path, requested_path);
    portEXIT_CRITICAL(&photo_mutex);
    /* A 201.9-second physical transfer accumulated a same-path retry. Treat
     * its published epoch as ready without allocating a second 18 KiB frame;
     * the worker never reads the LVGL-owned active descriptor or pointer. */
    if (ready) return true;
    PhotoRequest request;
    if (!request_begin(&request, path, guard, context)) return false;
    uint16_t *pixels = malloc(HQ_PHOTO_BYTES);
    bool restored = pixels && HQ_PhotoCacheLoad(user, path, pixels, request_current, &request) &&
                    publish_pixels(&request, pixels);
    if (!restored) free(pixels);
    worker_finished();
    portENTER_CRITICAL(&photo_mutex);
    if (restored) ++photo_stats.cache_hits;
    else ++photo_stats.cache_misses;
    portEXIT_CRITICAL(&photo_mutex);
    return restored;
}

static bool decode_staged(PhotoRequest *request, size_t length, uint8_t *dictionary,
                          size_t capacity, uint16_t **pixels, unsigned *stage)
{
    *stage = 7;
    *pixels = malloc(HQ_PHOTO_BYTES);
    if (!*pixels) return false;
    *stage = 2;
    HQ_PngStream *stream = HQ_PngPrepareWithDictionary(dictionary, capacity);
    if (!stream) return false;
    bool decoded = false;
    *stage = 7;
    if (!HQ_PngSetPixels(stream, *pixels)) goto done;
    uint8_t input[1024];
    for (size_t offset = 0; offset < length;) {
        size_t count = length - offset;
        if (count > sizeof(input)) count = sizeof(input);
        *stage = 16;
        if (!HQ_PhotoStageRead(offset, input, count, request_current, request)) goto done;
        *stage = 9;
        if (!HQ_PngFeed(stream, input, count)) goto done;
        offset += count;
    }
    *stage = 9;
    decoded = HQ_PngComplete(stream) && request_current(request);
done:
    HQ_PngDestroy(stream);
    return decoded;
}

static void close_photo_session(PhotoSession *session, PhotoErrors *errors)
{
    if (session->client) {
        esp_http_client_close(session->client);
        esp_http_client_cleanup(session->client);
        session->client = NULL;
    }
    if (errors) *errors = session->headers.errors;
}

static bool fetch_range(PhotoSession *session, PhotoRequest *request, const char *url, const char *bearer,
                        const char *apikey, size_t start, size_t end, size_t fixed_total,
                        const char *etag, char *first_etag, uint8_t *bytes,
                        size_t *total, size_t *count, unsigned *stage, unsigned *status,
                        PhotoErrors *errors, bool *retryable)
{
    char *authorization = NULL;
    PhotoHeaders *headers = &session->headers;
    memset(headers, 0, sizeof(*headers));
    bool success = false;
    *retryable = false;
    *count = 0;
    *status = 0;
    if (!session->client) {
        *stage = 3;
        authorization = calloc(1, strlen(bearer) + 8);
        if (!authorization) goto done;
        snprintf(authorization, strlen(bearer) + 8, "Bearer %s", bearer);
        /* IDF emits whole header lines. A 970-byte ordinary JWT made TX512 stop
         * before Authorization/terminator while open() still returned success. */
        int tx_capacity = HQ_HttpTxSize(bearer, apikey, 8192);
        if (!tx_capacity) goto done;
        esp_http_client_config_t config = {
            .url = url,
            .timeout_ms = 15000,
            .buffer_size = 2048,
            .buffer_size_tx = tx_capacity,
            .event_handler = photo_http_event,
            .user_data = headers,
            .crt_bundle_attach = esp_crt_bundle_attach,
            .disable_auto_redirect = true,
            .keep_alive_enable = false
        };
        *stage = 4;
        session->client = esp_http_client_init(&config);
        if (!session->client || esp_http_client_set_header(session->client, "Authorization", authorization) != ESP_OK ||
            esp_http_client_set_header(session->client, "apikey", apikey) != ESP_OK ||
            esp_http_client_set_header(session->client, "Accept-Encoding", "identity") != ESP_OK) goto done;
        /* set_header copies its value. Release the duplicate before certificate
         * verification reaches its heap peak; credentials never enter staging. */
        memset(authorization, 0, strlen(authorization));
        free(authorization);
        authorization = NULL;
    }
    char range[48];
    snprintf(range, sizeof(range), "bytes=%u-%u", (unsigned)start, (unsigned)end);
    *stage = 4;
    if (esp_http_client_set_header(session->client, "Range", range) != ESP_OK ||
        (etag && *etag && esp_http_client_set_header(session->client, "If-Match", etag) != ESP_OK)) goto done;
    /* SDK open()->connect()->prepare() resets the parser/header cursor even on
     * an existing connection. Keep one fully drained 4 KiB response at a time:
     * fresh handshakes for all 80 ranges made the physical transfer too slow. */
    *stage = 11;
    if (!request_current(request)) goto done;
    *stage = 5;
    if (esp_http_client_open(session->client, 0) != ESP_OK) { *retryable = true; goto done; }
    *stage = 6;
    int64_t length = esp_http_client_fetch_headers(session->client);
    int response_status = esp_http_client_get_status_code(session->client);
    *status = response_status >= 100 && response_status <= 999 ? (unsigned)response_status : 0;
    if (length < 0 || !*status) { *retryable = true; goto done; }
    size_t wanted = 0;
    /* SDK ignores a header callback's return code. Keep a separate invalid bit
     * so duplicate, oversized, compressed or changed responses fail closed. */
    if (response_status != 206 || headers->invalid || !headers->range_seen ||
        !HQ_PhotoRangeParse(headers->range, start, end, fixed_total, total, &wanted) ||
        (length > 0 && (size_t)length != wanted) ||
        (etag && ((headers->etag_seen && strcmp(etag, headers->etag)) ||
                  (!headers->etag_seen && *etag)))) goto done;
    for (;;) {
        *stage = 11;
        if (!request_current(request)) goto done;
        *stage = 8;
        /* The permanently borrowed 32 KiB window provides 4 KiB response
         * scratch plus one overflow byte without another heap/stack buffer. */
        size_t available = wanted + 1 - *count;
        int received = esp_http_client_read(session->client, (char *)bytes + *count, (int)available);
        if (received < 0) { *retryable = true; goto done; }
        if (!received) break;
        if ((size_t)received > available) goto done;
        *count += (size_t)received;
        if (*count > wanted) goto done;
    }
    *stage = 10;
    if (*count != wanted || !esp_http_client_is_complete_data_received(session->client)) {
        *retryable = true;
        goto done;
    }
    *stage = 11;
    if (!request_current(request)) goto done;
    if (first_etag) memcpy(first_etag, headers->etag, sizeof(headers->etag));
    success = true;
done:
    /* Never reuse a partially consumed/failed response. Its bytes remain in
     * scratch only; a bounded retry starts the same offset on fresh TLS. */
    if (!success || headers->connection_close) close_photo_session(session, NULL);
    if (authorization) memset(authorization, 0, strlen(authorization));
    free(authorization);
    *errors = headers->errors;
    return success;
}

bool HQ_PhotoDownload(const char *url, const char *bearer, const char *apikey,
                      const char *user, HQ_PhotoGuard guard, void *context,
                      uint8_t *dictionary, size_t dictionary_capacity)
{
    const char *path = url_path(url);
    if (!path || !bearer || !bearer[0] || !apikey || !apikey[0] ||
        strlen(bearer) > 8192 || strlen(apikey) > 8192 ||
        !user || !*user || strlen(user) >= 96) {
        download_result(false, 1, 0, NULL);
        return false;
    }
    PhotoRequest request;
    if (!request_begin(&request, path, guard, context)) {
        download_result(false, 11, 0, NULL);
        return false;
    }

    uint16_t *pixels = NULL;
    bool transferred = false, staged = false, success = false;
    size_t staged_bytes = 0, total = 0;
    unsigned stage = 2, http_status = 0;
    PhotoErrors errors = {0};
    PhotoSession session = {0};
    char etag[97] = {0};
    /* A physical cache miss left 111 KiB free but a largest block of 31 KiB,
     * so freeing/reallocating the inactive 32 KiB slot stranded core HTTP.
     * Borrow that permanent slot for response scratch, then PNG dictionary. */
    if (!dictionary || dictionary_capacity < 32768u) goto cleanup;
    /* Even without pixels/decoder, one 320 KiB HTTP transfer failed after
     * 235,880 bytes on the device; a fresh verified 4 KiB Range request passed.
     * Bound each response and stage only fully validated bytes. */
    stage = 13;
    staged = true;
    if (!HQ_PhotoStageBegin(request_current, &request)) goto cleanup;
    for (size_t offset = 0; !total || offset < total;) {
        size_t end = offset + 4095;
        if (total && end >= total) end = total - 1;
        size_t count = 0, received_total = 0;
        bool fetched = false;
        for (unsigned attempt = 0; attempt < 2; ++attempt) {
            bool retryable = false;
            stage = 11;
            if (!request_current(&request)) goto cleanup;
            fetched = fetch_range(&session, &request, url, bearer, apikey, offset, end, total,
                                  offset ? etag : NULL, offset ? NULL : etag,
                                  dictionary, &received_total, &count, &stage,
                                  &http_status, &errors, &retryable);
            if (fetched || !retryable) break;
            /* A failed range has never reached flash. Retry once with a fresh
             * verified client instead of reusing a broken TLS record stream. */
        }
        if (!fetched) goto cleanup;
        total = received_total;
        /* The exact response is fully drained before each bounded sector
         * write. An idle retained TLS connection has no body left to stage. */
        stage = 14;
        if (!HQ_PhotoStageWrite(dictionary, count, request_current, &request)) goto cleanup;
        offset += count;
    }
    close_photo_session(&session, &errors);
    stage = 15;
    if (!HQ_PhotoStageFinish(&staged_bytes, request_current, &request) || staged_bytes != total) goto cleanup;
    transferred = true;
cleanup:
    /* Retained TLS ends before flash readback, destination/context allocation
     * and decoding; cancellation and every error take this same cleanup path. */
    close_photo_session(&session, NULL);
    if (transferred && !request_current(&request)) stage = 11;
    if (transferred && request_current(&request) &&
        decode_staged(&request, staged_bytes, dictionary, dictionary_capacity, &pixels, &stage)) {
        /* TLS and decoder context are gone before CRC/readback and mailbox
         * transfer. The borrowed dictionary remains permanently service-owned. */
        bool saved = HQ_PhotoCacheSave(user, path, pixels, request_current, &request);
        portENTER_CRITICAL(&photo_mutex);
        if (saved) ++photo_stats.cache_saved;
        else ++photo_stats.cache_save_failed;
        portEXIT_CRITICAL(&photo_mutex);
        stage = 12;
        success = publish_pixels(&request, pixels);
        if (success) pixels = NULL;
    }
    if (staged) (void)HQ_PhotoStageDrop();
    free(pixels);
    worker_finished();
    download_result(success, stage, http_status, &errors);
    return success;
}
