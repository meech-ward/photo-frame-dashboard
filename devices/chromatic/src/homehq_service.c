/* Home HQ owns ordinary Auth, cached household data and desired-value writes.
 * The worker alone touches the network. LVGL receives projected wire copies;
 * a mutex protects brief queue/storage transitions, never an HTTPS operation. */
#include "homehq.h"
#include "homehq_pack.h"
#include "homehq_realtime.h"
#include "homehq_wire.h"
#include "homehq_projection.h"
#include "homehq_http.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <ctype.h>
#include <sys/time.h>
#ifdef HQ_SERVICE_HOST_TEST
#include "service_test_platform.h"
#else
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/event_groups.h"
#include "mbedtls/base64.h"
#endif

#define RESPONSE_MAX 32768u
#define CACHE_MAX 8192u
#define OUTBOX_MAX 32
#define WIFI_CONNECTED BIT0
#define SNAPSHOT_PERIOD_MS 3000
#define RETRY_MAX_MS 30000
#define CLOCK_MIN_EPOCH UINT64_C(1704067200)
#define CLOCK_MAX_EPOCH UINT64_C(4102444800)

static SemaphoreHandle_t guard;
static EventGroupHandle_t wifi_events;
static TaskHandle_t worker;
static nvs_handle_t store;
static bool store_ok, configured, session_durable, refresh_requested;
static bool wifi_initialized, sntp_started;
static volatile bool wifi_enabled;
static volatile unsigned latest_wifi_disconnect_reason;
static volatile bool radio_paused;
static int64_t last_clock_save_ms;
static bool clock_checkpointed;
static cJSON *config, *outbox, *configuration_intent;
static char *base_wire, *http_scratch;
static bool delivery_dirty;
static HQ_WireInfo base_info;
static bool logout_intent;
static cJSON *logout_credentials;
static unsigned generation, next_sequence;
static char status_text[80] = "Demo";
/* Access JWT and password exist only in RAM. NVS stores a renewal credential
 * plus its identity, so a stale cache can never become another account's home. */
static char *access_token, *refresh_token, *user_id;
static int64_t refresh_at_ms;
static char photo_request[192];
static unsigned photo_generation;
static bool photo_cache_clear_pending;
static int64_t photo_cache_clear_retry_at, photo_restore_retry_at;
static char photo_restore_path[192];
static unsigned photo_restore_generation;
typedef struct { unsigned generation; char user[96], home[96]; } PhotoContext;

static int64_t milliseconds(void) { return esp_timer_get_time() / 1000; }
static const cJSON *field(const cJSON *o, const char *k) { return cJSON_GetObjectItemCaseSensitive(o, k); }
static const char *string_field(const cJSON *o, const char *k)
{
    const cJSON *v = field(o, k);
    return cJSON_IsString(v) && v->valuestring ? v->valuestring : "";
}
static bool text_equal(const cJSON *o, const char *k, const char *s) { return !strcmp(string_field(o, k), s); }
static void set_status(const char *s) { snprintf(status_text, sizeof status_text, "%s", s); }
static void wipe_free(char *s)
{
    if (s) { volatile char *p = s; size_t n = strlen(s); while (n--) *p++ = 0; free(s); }
}
static void replace_string(char **slot, const char *s)
{
    char *copy = s && *s ? strdup(s) : NULL;
    wipe_free(*slot); *slot = copy;
}
static void wake_worker(void) { if (worker) xTaskNotifyGive(worker); }
static bool reserve_wire_buffers_locked(void);
static bool photo_current(void *opaque)
{
    PhotoContext *context = opaque;
    if (!context || !guard) return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    bool current = context->generation == generation && configured && session_durable &&
        !photo_cache_clear_pending && user_id && !strcmp(context->user, user_id) &&
        !strcmp(context->home, base_info.home);
    xSemaphoreGive(guard); return current;
}
static void clear_photo_cache_worker(void)
{
    xSemaphoreTake(guard, portMAX_DELAY);
    bool clear = photo_cache_clear_pending && milliseconds() >= photo_cache_clear_retry_at;
    xSemaphoreGive(guard);
    if (!clear) return;
    /* Flash cache work is serialized on this worker, outside the UI mutex.
     * A failed clear blocks only private-photo cache work, never household RPCs. */
    bool cleared = HQ_PhotoClearCache();
    xSemaphoreTake(guard, portMAX_DELAY);
    if (cleared && store_ok && nvs_set_u64(store, "photo_clear", 0) == ESP_OK && nvs_commit(store) == ESP_OK) photo_cache_clear_pending = false;
    else photo_cache_clear_retry_at = milliseconds() + 5000;
    xSemaphoreGive(guard);
}
static bool restore_photo_worker(unsigned request_generation)
{
    char path[sizeof photo_request]; PhotoContext context = {.generation = request_generation};
    xSemaphoreTake(guard, portMAX_DELAY);
    bool requested = request_generation == generation && configured && session_durable && user_id &&
        *base_info.home && !photo_cache_clear_pending && *photo_request && photo_generation == generation &&
        (photo_restore_generation != generation || strcmp(photo_restore_path, photo_request) || milliseconds() >= photo_restore_retry_at);
    if (requested) {
        snprintf(path, sizeof path, "%s", photo_request);
        snprintf(context.user, sizeof context.user, "%s", user_id);
        snprintf(context.home, sizeof context.home, "%s", base_info.home);
        snprintf(photo_restore_path, sizeof photo_restore_path, "%s", path);
        photo_restore_generation = generation; photo_restore_retry_at = milliseconds() + 10000;
    }
    xSemaphoreGive(guard);
    if (!requested) return false;
    /* Parking TLS gives cache restore its 18 KiB destination budget. Keep
     * both wire slots permanent: reclaiming one physically left 31,744-byte
     * holes and prevented a 32 KiB reserve from ever being recreated. */
    HQ_RTStop();
    /* A durable cached identity can display its decoded private frame while
     * Wi-Fi, UTC or access-token refresh is unavailable. No network is needed. */
    bool restored = HQ_PhotoRestore(context.user, path, photo_current, &context);
    bool current = photo_current(&context);
    xSemaphoreTake(guard, portMAX_DELAY);
    if (restored && current && photo_generation == generation && !strcmp(path, photo_request)) photo_request[0] = 0;
    xSemaphoreGive(guard);
    if (!current) HQ_PhotoReset();
    return restored && current;
}
static const char empty_wire[] = "{\"schema_version\":1,\"revision\":0,\"server_time\":0,\"home\":{\"id\":\"signed-out\",\"demo\":false},\"viewer\":{},\"people\":[],\"events\":[],\"chores\":[],\"shopping\":[],\"photos\":[],\"devices\":[],\"members\":[],\"agents\":[]}";
static bool reserve_wire_buffers_locked(void)
{
    /* A joined physical device had 84 KiB free but no block larger than
     * 23,552 bytes; its valid 25,482-byte HTTPS snapshot could not grow.
     * Reserve both bounded wire slots before Wi-Fi/LVGL fragment the heap. */
    if (!base_wire) {
        base_wire = calloc(1, RESPONSE_MAX + 1);
        if (!base_wire) return false;
    }
    if (!http_scratch) http_scratch = calloc(1, RESPONSE_MAX + 1);
    return http_scratch != NULL;
}
static void replace_base_wire_locked(const char *wire)
{
    size_t length = strlen(wire);
    if (length > RESPONSE_MAX || !base_wire) { set_status("Low memory. Retry."); return; }
    memcpy(base_wire, wire, length + 1);
    HQ_WireValidate(base_wire, strlen(base_wire), &base_info);
}
static const char *section(const char *kind)
{
    return !strcmp(kind, "chore") ? "chores" : !strcmp(kind, "shopping") ? "shopping" : !strcmp(kind, "device") ? "devices" : "";
}
static cJSON *find_row(cJSON *snapshot, const cJSON *command)
{
    cJSON *rows = cJSON_GetObjectItemCaseSensitive(snapshot, section(string_field(command, "kind")));
    cJSON *row;
    cJSON_ArrayForEach(row, rows) if (text_equal(row, "id", string_field(command, "id"))) return row;
    return NULL;
}
static void set_copy(cJSON *object, const char *key, const cJSON *value)
{
    cJSON *copy = cJSON_Duplicate(value, true);
    if (!copy) return;
    if (field(object, key)) cJSON_ReplaceItemInObjectCaseSensitive(object, key, copy);
    else cJSON_AddItemToObject(object, key, copy);
}
static void apply(cJSON *snapshot, const cJSON *command)
{
    cJSON *row = find_row(snapshot, command);
    if (!row) return;
    if (text_equal(command, "kind", "device")) {
        const cJSON *v;
        cJSON *destination = cJSON_GetObjectItemCaseSensitive(row, "state");
        if (!cJSON_IsObject(destination)) destination = row;
        cJSON_ArrayForEach(v, field(command, "state")) if (v->string) set_copy(destination, v->string, v);
    } else {
        set_copy(row, "done", field(command, "done"));
        if (field(command, "done_by")) set_copy(row, "done_by", field(command, "done_by"));
    }
}
static void publish_locked(void)
{
    /* The canonical wire stays in its reserved slot. A dirty flag avoids a
     * third 25 KiB allocation; LVGL asks for only its current page's bytes. */
    delivery_dirty = base_wire != NULL;
}
static bool nvs_erase_owned(const char *key)
{
    esp_err_t e = nvs_erase_key(store, key);
    return e == ESP_OK || e == ESP_ERR_NVS_NOT_FOUND;
}
static bool save_json(const char *key, const cJSON *json)
{
    if (!store_ok) return false;
    char *s = cJSON_PrintUnformatted(json);
    if (!s) return false;
    esp_err_t e = nvs_set_str(store, key, s);
    /* Configuration may contain the Wi-Fi password, and session has refresh
     * credentials; erase serialization scratch instead of leaving it in heap. */
    wipe_free(s);
    return e == ESP_OK && nvs_commit(store) == ESP_OK;
}
static cJSON *read_json(const char *key, size_t maximum)
{
    size_t n = 0;
    if (!store_ok || nvs_get_str(store, key, NULL, &n) != ESP_OK || !n || n > maximum) return NULL;
    char *s = calloc(1, n);
    if (!s) return NULL;
    cJSON *value = nvs_get_str(store, key, s, &n) == ESP_OK ? cJSON_Parse(s) : NULL;
    wipe_free(s);
    return value;
}
static bool save_outbox_locked(void)
{
    cJSON *record = cJSON_CreateObject();
    if (!record) return false;
    cJSON_AddStringToObject(record, "user_id", user_id ? user_id : "");
    cJSON_AddItemToObject(record, "pending", cJSON_Duplicate(outbox, true));
    bool ok = save_json("outbox", record);
    cJSON_Delete(record);
    return ok;
}
static bool clock_valid(uint64_t epoch)
{
    return epoch >= CLOCK_MIN_EPOCH && epoch <= CLOCK_MAX_EPOCH;
}
static bool save_clock_locked(uint64_t epoch, bool force)
{
    int64_t now = milliseconds();
    if (!force && clock_checkpointed && now - last_clock_save_ms < 3600000) return true;
    if (!store_ok || nvs_set_u64(store, "clock", epoch) != ESP_OK || nvs_commit(store) != ESP_OK) return false;
    last_clock_save_ms = now; clock_checkpointed = true; return true;
}
static bool apply_clock(uint64_t epoch)
{
    if (!clock_valid(epoch)) return false;
    struct timeval time_value = {.tv_sec = (time_t)epoch, .tv_usec = 0};
    return settimeofday(&time_value, NULL) == 0;
}
static void restore_clock_locked(void)
{
    uint64_t checkpoint = 0;
    if (store_ok && nvs_get_u64(store, "clock", &checkpoint) == ESP_OK && apply_clock(checkpoint)) {
        last_clock_save_ms = milliseconds(); clock_checkpointed = true;
    }
}
static void restore_photo_clear_locked(void)
{
    uint64_t intent = 0;
    photo_cache_clear_pending = store_ok && nvs_get_u64(store, "photo_clear", &intent) == ESP_OK && intent != 0;
    photo_cache_clear_retry_at = 0;
}
static bool save_session_locked(void)
{
    if (!refresh_token || !user_id) return false;
    cJSON *record = cJSON_CreateObject();
    if (!record) return false;
    cJSON_AddNumberToObject(record, "v", 1);
    cJSON_AddStringToObject(record, "refresh_token", refresh_token);
    cJSON_AddStringToObject(record, "user_id", user_id);
    bool ok = save_json("session", record);
    cJSON *renewal = cJSON_GetObjectItemCaseSensitive(record, "refresh_token");
    if (cJSON_IsString(renewal)) memset(renewal->valuestring, 0, strlen(renewal->valuestring));
    cJSON_Delete(record);
    session_durable = ok;
    if (!ok) set_status("Session not saved. Free storage.");
    return ok;
}
static bool save_cache_candidate(const char *candidate, unsigned request_generation)
{
    uint8_t *packed = malloc(CACHE_MAX);
    if (!packed || !store_ok) { free(packed); return false; }
    /* The worker's inactive HTTP slot stays stable while UI account changes
     * affect only canonical. Compress before swapping slots: this removes
     * ~49 KiB of old scratch without making buttons wait for dictionary work. */
    HQ_WireInfo info;
    size_t bytes = 0;
    bool encoded = candidate && candidate == http_scratch && HQ_WireValidate(candidate, strlen(candidate), &info) && *info.home &&
        HQ_PackInto(candidate, strlen(candidate), packed, CACHE_MAX, &bytes) && bytes;
    xSemaphoreTake(guard, portMAX_DELAY);
    bool current = request_generation == generation && user_id && encoded && !strcmp(info.viewer, user_id);
    bool ok = current &&
        nvs_set_blob(store, "cache", packed, bytes) == ESP_OK &&
        nvs_set_str(store, "cache_user", user_id) == ESP_OK && nvs_commit(store) == ESP_OK;
    if (current && !ok) {
        nvs_erase_owned("cache"); nvs_erase_owned("cache_user"); nvs_commit(store);
        set_status("Connected. Cache full.");
    }
    xSemaphoreGive(guard);
    free(packed); return ok;
}
static char *load_cache_locked(void)
{
    char identity[96] = {0}; size_t n = sizeof identity;
    if (!user_id || nvs_get_str(store, "cache_user", identity, &n) != ESP_OK || strcmp(identity, user_id)) return NULL;
    size_t packed_length = 0;
    if (nvs_get_blob(store, "cache", NULL, &packed_length) != ESP_OK || !packed_length || packed_length > CACHE_MAX) return NULL;
    uint8_t *packed = malloc(packed_length);
    if (!packed) return NULL;
    size_t decoded = 0;
    char *wire = nvs_get_blob(store, "cache", packed, &packed_length) == ESP_OK ? HQ_Unpack(packed, packed_length, &decoded) : NULL;
    free(packed);
    HQ_WireInfo info;
    if (!wire || !HQ_WireValidate(wire, decoded, &info) || !*info.home || strcmp(info.viewer, user_id)) { free(wire); return NULL; }
    return wire;
}
static bool clear_identity_locked(void)
{
    if (!store_ok) return false;
    /* Persist intent before acknowledging logout/setup. A reset before the
     * worker invalidates both flash headers must still purge the old frame. */
    if (nvs_set_u64(store, "photo_clear", 1) != ESP_OK) return false;
    photo_cache_clear_pending = true; photo_cache_clear_retry_at = 0;
    /* Erase exact app-owned entries, never factory settings, Wi-Fi/project
     * configuration or a different application's state. */
    bool ok = nvs_erase_owned("session") && nvs_erase_owned("cache") &&
              nvs_erase_owned("cache_user") && nvs_erase_owned("outbox");
    if (!ok || nvs_commit(store) != ESP_OK) { set_status("Session not cleared. Free storage."); return false; }
    replace_string(&access_token, NULL); replace_string(&refresh_token, NULL); replace_string(&user_id, NULL);
    session_durable = false; refresh_at_ms = 0;
    cJSON_Delete(outbox); outbox = cJSON_CreateArray();
    photo_request[0] = photo_restore_path[0] = 0;
    photo_cache_clear_pending = true; photo_cache_clear_retry_at = 0; HQ_PhotoReset();
    return true;
}
static bool ordinary_key(const char *key)
{
    if (!strncmp(key, "sb_publishable_", 15)) return strlen(key) < 2048;
    /* Legacy clients may use an anon JWT. A service-role key must never become
     * a portable household client's embedded authorization credential. */
    const char *dot = strchr(key, '.');
    const char *end = dot ? strchr(dot + 1, '.') : NULL;
    if (!dot || !end || end - dot > 1536) return false;
    char b64[1540]; size_t len = (size_t)(end - dot - 1);
    memcpy(b64, dot + 1, len);
    for (size_t i = 0; i < len; ++i) { if (b64[i] == '-') b64[i] = '+'; else if (b64[i] == '_') b64[i] = '/'; }
    while (len % 4) b64[len++] = '=';
    b64[len] = 0;
    unsigned char decoded[1156]; size_t actual = 0;
    if (mbedtls_base64_decode(decoded, sizeof decoded - 1, &actual, (unsigned char *)b64, len)) return false;
    decoded[actual] = 0;
    cJSON *claims = cJSON_Parse((char *)decoded);
    bool ok = claims && text_equal(claims, "role", "anon");
    cJSON_Delete(claims); return ok;
}
static bool safe_url(const char *url)
{
    if (strncmp(url, "https://", 8) || strlen(url) > 240) return false;
    const char *host = url + 8;
    if (!*host || strchr(host, '@') || strchr(host, '?') || strchr(host, '#')) return false;
    /* Provisioning accepts only a base origin, preventing bearer credentials
     * from following an accidental arbitrary-path or redirect destination. */
    for (const char *p = host; *p; ++p) if (!(isalnum((unsigned char)*p) || *p == '.' || *p == '-' || *p == ':')) return false;
    return true;
}
static bool valid_command(const cJSON *c)
{
    if (!cJSON_IsObject(c)) return false;
    const char *kind = string_field(c, "kind"), *id = string_field(c, "id");
    const cJSON *version = field(c, "version");
    if (!*section(kind) || !*id || strlen(id) > 80 || !cJSON_IsNumber(version) || version->valuedouble < 1 || version->valuedouble != version->valueint) return false;
    if (!strcmp(kind, "device")) {
        const cJSON *state = field(c, "state"), *v; unsigned count = 0;
        if (!cJSON_IsObject(state)) return false;
        cJSON_ArrayForEach(v, state) {
            ++count;
            if (!v->string) return false;
            if (!strcmp(v->string, "on") || !strcmp(v->string, "locked")) { if (!cJSON_IsBool(v)) return false; }
            else if (!strcmp(v->string, "level")) { if (!cJSON_IsNumber(v) || v->valuedouble < 0 || v->valuedouble > 100) return false; }
            else if (!strcmp(v->string, "state")) { if (!cJSON_IsString(v) || (strcmp(v->valuestring, "open") && strcmp(v->valuestring, "closed"))) return false; }
            else return false;
        }
        if (!count || count > 2) return false;
    } else if (!cJSON_IsBool(field(c, "done"))) return false;
    const cJSON *person = field(c, "done_by");
    return !person || cJSON_IsNull(person) || (cJSON_IsString(person) && strlen(person->valuestring) <= 80);
}
static cJSON *bounded_command(const cJSON *input)
{
    cJSON *c = cJSON_CreateObject();
    if (!c) return NULL;
    const char *keys[] = {"kind", "id", "done", "state", "version", "done_by"};
    for (unsigned i = 0; i < sizeof keys / sizeof keys[0]; ++i) if (field(input, keys[i])) set_copy(c, keys[i], field(input, keys[i]));
    return c;
}

/* A bounded body callback covers both Content-Length and chunked responses.
 * Provider error bodies are never surfaced or logged because they can echo
 * credentials. HTTP redirects are disabled rather than forwarding a JWT. */
typedef struct { char *data; size_t length, capacity; bool overflow; } response_t;
static esp_err_t http_event(esp_http_client_event_t *event)
{
    response_t *r = event->user_data;
    if (event->event_id != HTTP_EVENT_ON_DATA || event->data_len <= 0) return ESP_OK;
    size_t total = r->length + (size_t)event->data_len;
    if (total > RESPONSE_MAX) { r->overflow = true; return ESP_FAIL; }
    if (!r->data || total + 1 > r->capacity) { r->overflow = true; return ESP_FAIL; }
    memcpy(r->data + r->length, event->data, event->data_len);
    r->length = total; r->data[total] = 0;
    return ESP_OK;
}
/* The response borrows the worker's inactive reserved slot. It must never be
 * freed: Auth parses then scrubs it, while a valid snapshot swaps the slots. */
static char *http_body(const cJSON *cfg, const char *jwt, const char *path, const cJSON *body, int *status)
{
    *status = 0;
    xSemaphoreTake(guard, portMAX_DELAY);
    bool reserved = reserve_wire_buffers_locked();
    xSemaphoreGive(guard);
    if (!reserved) return NULL;
    http_scratch[0] = 0;
    const char *origin = string_field(cfg, "url"), *key = string_field(cfg, "key");
    const char *token = jwt && *jwt ? jwt : key;
    unsigned tx_size = HQ_HttpTxSize(token, key, 4096);
    if (!tx_size) return NULL;
    char url[512];
    if (snprintf(url, sizeof url, "%s%s", origin, path) >= (int)sizeof url) return NULL;
    char *payload = body ? cJSON_PrintUnformatted(body) : strdup("");
    if (!payload) return NULL;
    response_t response = {.data = http_scratch, .capacity = RESPONSE_MAX + 1};
    esp_http_client_config_t settings = {.url = url, .method = HTTP_METHOD_POST,
        .timeout_ms = 12000, .event_handler = http_event, .user_data = &response,
        .crt_bundle_attach = esp_crt_bundle_attach, .disable_auto_redirect = true,
        .buffer_size = 1024, .buffer_size_tx = (int)tx_size};
    esp_http_client_handle_t client = esp_http_client_init(&settings);
    if (!client) { wipe_free(payload); return NULL; }
    bool prepared = esp_http_client_set_header(client, "apikey", key) == ESP_OK &&
        esp_http_client_set_header(client, "Content-Type", "application/json") == ESP_OK &&
        esp_http_client_set_header(client, "X-Supabase-Api-Version", "2024-01-01") == ESP_OK;
    size_t auth_length = strlen(token) + 8;
    char *authorization = malloc(auth_length);
    if (authorization) {
        snprintf(authorization, auth_length, "Bearer %s", token);
        prepared = prepared && esp_http_client_set_header(client, "Authorization", authorization) == ESP_OK;
    }
    esp_http_client_set_post_field(client, payload, strlen(payload));
    esp_err_t result = authorization && prepared ? esp_http_client_perform(client) : ESP_ERR_NO_MEM;
    if (result == ESP_OK && !response.overflow) *status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    wipe_free(authorization); wipe_free(payload);
    if (!*status || !response.length) { memset(response.data, 0, response.length); return NULL; }
    return response.data;
}
static cJSON *http_json(const cJSON *cfg, const char *jwt, const char *path, const cJSON *body, int *status)
{
    char *wire = http_body(cfg, jwt, path, body, status);
    cJSON *value = wire ? cJSON_Parse(wire) : NULL;
    if (wire) memset(wire, 0, strlen(wire));
    return value;
}
static void wifi_event(void *unused, esp_event_base_t event, int32_t id, void *data)
{
    (void)unused; (void)data;
    if (event == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(wifi_events, WIFI_CONNECTED); wake_worker();
    } else if (event == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *disconnected = data;
        latest_wifi_disconnect_reason = disconnected ? disconnected->reason : 0;
        xEventGroupClearBits(wifi_events, WIFI_CONNECTED);
        if (wifi_enabled && !radio_paused) esp_wifi_connect();
        wake_worker();
    } else if (event == WIFI_EVENT && id == WIFI_EVENT_STA_START && wifi_enabled && !radio_paused) esp_wifi_connect();
}
static bool start_wifi(const cJSON *cfg)
{
    wifi_enabled = false;
    if (wifi_initialized) esp_wifi_stop();
    else {
        esp_err_t e = esp_netif_init();
        if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) return false;
        e = esp_event_loop_create_default();
        if (e != ESP_OK && e != ESP_ERR_INVALID_STATE) return false;
        if (!esp_netif_create_default_wifi_sta()) return false;
        wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
        if (esp_wifi_init(&init) != ESP_OK || esp_wifi_set_storage(WIFI_STORAGE_RAM) != ESP_OK ||
            esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL) != ESP_OK ||
            esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL) != ESP_OK) return false;
        wifi_initialized = true;
    }
    wifi_config_t wifi = {0};
    const char *ssid = string_field(cfg, "wifi_ssid"), *password = string_field(cfg, "wifi_password");
    memcpy(wifi.sta.ssid, ssid, strlen(ssid)); memcpy(wifi.sta.password, password, strlen(password));
    xEventGroupClearBits(wifi_events, WIFI_CONNECTED);
    if (esp_wifi_set_mode(WIFI_MODE_STA) != ESP_OK || esp_wifi_set_config(WIFI_IF_STA, &wifi) != ESP_OK) return false;
    wifi_enabled = !radio_paused;
    if (esp_wifi_start() != ESP_OK) { wifi_enabled = false; return false; }
    esp_wifi_set_ps(WIFI_PS_NONE);
    if (!sntp_started) {
#if CONFIG_LWIP_SNTP_MAX_SERVERS >= 3
        esp_sntp_config_t settings = ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE(3,
            ESP_SNTP_SERVER_LIST("time.cloudflare.com", "time.google.com", "pool.ntp.org"));
#else
        esp_sntp_config_t settings = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
#endif
        sntp_started = esp_netif_sntp_init(&settings) == ESP_OK;
    }
    return true;
}
static bool auth_install(cJSON *response, unsigned request_generation, bool password_login)
{
    const char *jwt = string_field(response, "access_token"), *renewal = string_field(response, "refresh_token");
    const char *identity = string_field(field(response, "user"), "id");
    const cJSON *expires = field(response, "expires_in");
    if (!*jwt || strlen(jwt) > 4096 || !*renewal || strlen(renewal) > 1024 ||
        (!*identity && password_login) || strlen(identity) > 80 || !cJSON_IsNumber(expires) || expires->valueint < 1) return false;
    for (const char *p = jwt; *p; ++p) if (*p <= ' ' || *p > '~') return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    bool ok = request_generation == generation;
    if (ok) {
        if (!*identity) identity = user_id;
        if (!identity || !*identity || (user_id && strcmp(user_id, identity))) ok = false;
    }
    if (!ok && request_generation == generation) set_status("Sign-in account does not match queued changes");
    if (ok) {
        replace_string(&access_token, jwt); replace_string(&refresh_token, renewal); replace_string(&user_id, identity);
        int lifespan = expires->valueint;
        refresh_at_ms = milliseconds() + (int64_t)(lifespan > 120 ? lifespan - 120 : lifespan / 2) * 1000;
        session_durable = false;
        ok = access_token && refresh_token && user_id && save_session_locked();
        refresh_requested = true;
        if (ok) set_status("Connected");
    }
    xSemaphoreGive(guard);
    return ok;
}
static bool session_lost(int status, const cJSON *response)
{
    if (status != 400) return false;
    const char *code = string_field(response, "code");
    if (!*code) code = string_field(response, "error_code");
    return !strcmp(code, "refresh_token_not_found") || !strcmp(code, "refresh_token_already_used") ||
           !strcmp(code, "session_not_found") || !strcmp(code, "session_expired");
}
static bool authenticate(const cJSON *cfg, const cJSON *login, unsigned request_generation, bool *terminal)
{
    *terminal = false;
    cJSON *body = cJSON_CreateObject();
    if (!body) return false;
    const char *path;
    bool password_login = login && *string_field(login, "email");
    if (password_login) {
        cJSON_AddStringToObject(body, "email", string_field(login, "email"));
        cJSON_AddStringToObject(body, "password", string_field(login, "password"));
        path = "/auth/v1/token?grant_type=password";
    } else {
        xSemaphoreTake(guard, portMAX_DELAY);
        if (refresh_token) cJSON_AddStringToObject(body, "refresh_token", refresh_token);
        xSemaphoreGive(guard);
        path = "/auth/v1/token?grant_type=refresh_token";
    }
    int status;
    cJSON *response = http_json(cfg, NULL, path, body, &status);
    /* The password body and intent are temporary, never part of config/cache. */
    cJSON *password = cJSON_GetObjectItemCaseSensitive(body, "password");
    if (cJSON_IsString(password)) memset(password->valuestring, 0, strlen(password->valuestring));
    cJSON_Delete(body);
    bool ok = status >= 200 && status < 300 && cJSON_IsObject(response) && auth_install(response, request_generation, password_login);
    *terminal = password_login && ((status >= 200 && status < 300) || status == 400 || status == 401 || status == 403);
    if (!ok) {
        xSemaphoreTake(guard, portMAX_DELAY);
        if (request_generation == generation) {
            if (session_lost(status, response)) {
                /* A lost renewal token needs a fresh ordinary sign-in. Pending
                 * writes/cache stay account-bound until explicitly cleared. */
                replace_string(&access_token, NULL); replace_string(&refresh_token, NULL);
                nvs_erase_owned("session"); nvs_commit(store); session_durable = false;
                set_status("Sign in again");
            } else if (password_login && (status == 400 || status == 401 || status == 403)) set_status("Sign-in failed");
            else if (!session_durable && access_token) set_status("Session not saved. Free storage.");
            else set_status(status ? "Authentication unavailable" : "Offline. Retrying.");
        }
        xSemaphoreGive(guard);
    }
    cJSON *rotated = cJSON_GetObjectItemCaseSensitive(response, "refresh_token");
    if (cJSON_IsString(rotated)) memset(rotated->valuestring, 0, strlen(rotated->valuestring));
    cJSON *jwt_response = cJSON_GetObjectItemCaseSensitive(response, "access_token");
    if (cJSON_IsString(jwt_response)) memset(jwt_response->valuestring, 0, strlen(jwt_response->valuestring));
    cJSON_Delete(response);
    return ok;
}
static void prune_missing_locked(void)
{
    for (int i = cJSON_GetArraySize(outbox) - 1; i >= 0; --i) {
        const cJSON *command = cJSON_GetArrayItem(outbox, i);
        if (!HQ_WireHasRow(base_wire, strlen(base_wire), section(string_field(command, "kind")), string_field(command, "id")))
            cJSON_DeleteItemFromArray(outbox, i);
    }
}
static bool install_snapshot_wire(char *wire, unsigned request_generation)
{
    HQ_WireInfo info;
    if (!wire || wire != http_scratch || !HQ_WireValidate(wire, strlen(wire), &info)) return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    bool ok = request_generation == generation && user_id && !strcmp(info.viewer, user_id) && *info.home;
    if (ok) {
        /* Keep the old canonical slot intact until the complete bounded reply
         * passes syntax, identity and generation checks. No wire is copied. */
        char *old = base_wire; base_wire = wire; http_scratch = old; base_info = info;
        /* This timestamp arrived through normally verified HTTPS. Keep a
         * boot checkpoint at most hourly; public SNTP still corrects real time. */
        if (info.server_time > 0 && apply_clock((uint64_t)info.server_time))
            save_clock_locked((uint64_t)info.server_time, false);
        prune_missing_locked();
        bool queue_saved = save_outbox_locked();
        set_status(!queue_saved ? "Changes not saved. Free storage." : "Connected");
    }
    xSemaphoreGive(guard); return ok;
}
static bool acknowledge_locked(const cJSON *sent, const cJSON *reply)
{
    const cJSON *row = field(reply, "item");
    const char *result = string_field(reply, "status");
    const cJSON *version = field(row, "version");
    if ((!strcmp(result, "saved") || !strcmp(result, "conflict")) && cJSON_IsObject(row) &&
        cJSON_IsNumber(version) && version->valuedouble >= 1 && text_equal(row, "id", string_field(sent, "id"))) {
        for (int i = 0; i < cJSON_GetArraySize(outbox); ++i) {
            cJSON *pending = cJSON_GetArrayItem(outbox, i);
            if (!text_equal(pending, "kind", string_field(sent, "kind")) || !text_equal(pending, "id", string_field(sent, "id"))) continue;
            const cJSON *a = field(pending, "sequence"), *b = field(sent, "sequence");
            /* A contradictory stale version yields to the authoritative row.
             * A newer local press during a saved request keeps its desired value
             * and advances to the acknowledged version before the next RPC. */
            if (!strcmp(result, "conflict") || (a && b && a->valuedouble == b->valuedouble)) cJSON_DeleteItemFromArray(outbox, i);
            else if (field(row, "version")) set_copy(pending, "version", field(row, "version"));
            break;
        }
        if (!save_outbox_locked()) set_status("Changes not saved. Free storage.");
        else set_status(!strcmp(result, "conflict") ? "Changed elsewhere. Reloaded." : "Saved");
        refresh_requested = true; return true;
    }
    set_status("Save unavailable. Retrying."); return false;
}
static cJSON *rpc_body(const cJSON *command, const char **path)
{
    cJSON *body = cJSON_CreateObject();
    if (!body) return NULL;
    cJSON_AddStringToObject(body, "p_id", string_field(command, "id"));
    set_copy(body, "p_version", field(command, "version"));
    if (text_equal(command, "kind", "device")) {
        *path = "/rest/v1/rpc/homehq_set_device";
        set_copy(body, "p_state", field(command, "state"));
    } else {
        *path = "/rest/v1/rpc/homehq_set_done";
        cJSON_AddStringToObject(body, "p_kind", string_field(command, "kind"));
        set_copy(body, "p_done", field(command, "done"));
        if (field(command, "done_by")) set_copy(body, "p_done_by", field(command, "done_by"));
    }
    return body;
}
static void scrub_login(cJSON *login)
{
    cJSON *v = cJSON_GetObjectItemCaseSensitive(login, "password");
    if (cJSON_IsString(v)) memset(v->valuestring, 0, strlen(v->valuestring));
    cJSON_Delete(login);
}
static void revoke_local_session(const cJSON *cfg, cJSON *credentials)
{
    /* Local erase is unconditional and already complete. When connected, revoke
     * this ordinary Auth session too; a lost network response cannot restore
     * credentials, cache or pending writes on the signed-out device. */
    const char *jwt = string_field(credentials, "access_token");
    cJSON *renewed = NULL;
    if (!*jwt && *string_field(credentials, "refresh_token")) {
        cJSON *body = cJSON_CreateObject();
        if (body) {
            cJSON_AddStringToObject(body, "refresh_token", string_field(credentials, "refresh_token"));
            int status = 0;
            renewed = http_json(cfg, NULL, "/auth/v1/token?grant_type=refresh_token", body, &status);
            cJSON *token_value = cJSON_GetObjectItemCaseSensitive(body, "refresh_token");
            if (cJSON_IsString(token_value)) memset(token_value->valuestring, 0, strlen(token_value->valuestring));
            cJSON_Delete(body);
            if (status >= 200 && status < 300) jwt = string_field(renewed, "access_token");
        }
    }
    if (*jwt) { int status = 0; cJSON *reply = http_json(cfg, jwt, "/auth/v1/logout?scope=local", NULL, &status); cJSON_Delete(reply); }
    const char *keys[] = {"access_token", "refresh_token"};
    for (unsigned i = 0; i < sizeof keys / sizeof keys[0]; ++i) {
        cJSON *a = cJSON_GetObjectItemCaseSensitive(credentials, keys[i]);
        cJSON *b = cJSON_GetObjectItemCaseSensitive(renewed, keys[i]);
        if (cJSON_IsString(a)) memset(a->valuestring, 0, strlen(a->valuestring));
        if (cJSON_IsString(b)) memset(b->valuestring, 0, strlen(b->valuestring));
    }
    cJSON_Delete(renewed);
}
static void service_worker(void *unused)
{
    (void)unused;
    /* Main must finish the first panel before Wi-Fi and TLS reserve their
     * buffers; task creation can otherwise preempt the lower-priority boot. */
    vTaskDelay(pdMS_TO_TICKS(300));
    unsigned retry_ms = 1000;
    int64_t next_snapshot = 0, retry_at = 0;
    cJSON *login = NULL;
    unsigned login_generation = 0;
    while (true) {
        xSemaphoreTake(guard, portMAX_DELAY);
        cJSON *intent = configuration_intent; configuration_intent = NULL;
        bool logging_out = logout_intent; logout_intent = false;
        cJSON *departing = logout_credentials; logout_credentials = NULL;
        unsigned current_generation = generation;
        cJSON *cfg = cJSON_Duplicate(config, true);
        bool ready = configured;
        xSemaphoreGive(guard);
        clear_photo_cache_worker();
        if (logging_out) {
            HQ_RTStop();
            if (cfg && departing && (xEventGroupGetBits(wifi_events) & WIFI_CONNECTED) && time(NULL) >= 1704067200)
                revoke_local_session(cfg, departing);
            else if (departing) {
                const char *keys[] = {"access_token", "refresh_token"};
                for (unsigned i = 0; i < 2; ++i) { cJSON *v = cJSON_GetObjectItemCaseSensitive(departing, keys[i]); if (cJSON_IsString(v)) memset(v->valuestring, 0, strlen(v->valuestring)); }
            }
            cJSON_Delete(departing); departing = NULL;
            /* Local credentials/data were already erased. Remote revocation is
             * best effort and never delays the safe demo screen. */
            scrub_login(login); login = NULL;
            next_snapshot = retry_at = 0;
        }
        if (intent) {
            HQ_RTStop();
            scrub_login(login); login = intent; login_generation = current_generation;
            cJSON_Delete(cfg);
            xSemaphoreTake(guard, portMAX_DELAY); cfg = cJSON_Duplicate(config, true); xSemaphoreGive(guard);
            bool wifi_ok = cfg && start_wifi(cfg);
            xSemaphoreTake(guard, portMAX_DELAY);
            if (current_generation == generation) set_status(wifi_ok ? "Connecting" : "Wi-Fi unavailable");
            xSemaphoreGive(guard);
            next_snapshot = retry_at = 0; retry_ms = 1000;
        } else if (ready && !wifi_initialized && cfg) start_wifi(cfg);
        if (restore_photo_worker(current_generation)) { cJSON_Delete(cfg); continue; }
        if (!ready || !cfg) { HQ_RTStop(); cJSON_Delete(cfg); ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1000)); continue; }
        bool connected = (xEventGroupGetBits(wifi_events) & WIFI_CONNECTED) != 0;
        int64_t now = milliseconds();
        if (!connected || time(NULL) < 1704067200 || now < retry_at) {
            if (!connected) HQ_RTStop();
            xSemaphoreTake(guard, portMAX_DELAY);
            if (current_generation == generation && now >= retry_at) set_status(!connected ? (radio_paused ? "Radio paused. Changes queued." : "Offline. Changes queued.") : "Syncing time for HTTPS");
            xSemaphoreGive(guard);
            cJSON_Delete(cfg); ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1000)); continue;
        }
        xSemaphoreTake(guard, portMAX_DELAY);
        bool authenticate_now = login || (refresh_token && (!access_token || now >= refresh_at_ms));
        bool checkpoint_now = access_token && !session_durable;
        bool authorized = access_token && session_durable;
        xSemaphoreGive(guard);
        if (checkpoint_now) {
            xSemaphoreTake(guard, portMAX_DELAY); save_session_locked(); xSemaphoreGive(guard);
            cJSON_Delete(cfg); ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(3000)); continue;
        }
        if (authenticate_now) {
            bool terminal = false;
            bool ok = authenticate(cfg, login, current_generation, &terminal);
            xSemaphoreTake(guard, portMAX_DELAY); bool superseded = login_generation != generation; xSemaphoreGive(guard);
            if (login && (terminal || superseded)) { scrub_login(login); login = NULL; }
            if (!ok) { retry_at = milliseconds() + retry_ms; retry_ms = retry_ms < RETRY_MAX_MS / 2 ? retry_ms * 2 : RETRY_MAX_MS; }
            else { retry_at = 0; retry_ms = 1000; }
            cJSON_Delete(cfg); continue;
        }
        if (!authorized) {
            HQ_RTStop();
            xSemaphoreTake(guard, portMAX_DELAY);
            if (current_generation == generation && !login) set_status("Sign in to your home");
            xSemaphoreGive(guard);
            cJSON_Delete(cfg); ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1000)); continue;
        }
        if (!http_scratch) HQ_RTStop();
        xSemaphoreTake(guard, portMAX_DELAY);
        bool wire_ready = reserve_wire_buffers_locked();
        if (!wire_ready) set_status("Low memory. Retry.");
        xSemaphoreGive(guard);
        if (!wire_ready) { cJSON_Delete(cfg); ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1000)); continue; }
        xSemaphoreTake(guard, portMAX_DELAY);
        char *jwt = access_token ? strdup(access_token) : NULL;
        char home[96]; snprintf(home, sizeof home, "%s", base_info.home);
        PhotoContext photo_context = {.generation = current_generation};
        snprintf(photo_context.user, sizeof photo_context.user, "%s", user_id ? user_id : "");
        snprintf(photo_context.home, sizeof photo_context.home, "%s", base_info.home);
        xSemaphoreGive(guard);
        if (jwt && *home) { HQ_RTConfigure(string_field(cfg, "url"), string_field(cfg, "key"), home, jwt); HQ_RTPoll(); }
        else HQ_RTStop();
        /* A socket lost after a 60-second joined poll must promptly resume
         * fallback polling rather than retaining the old joined deadline. */
        int64_t fallback_deadline = milliseconds() + SNAPSHOT_PERIOD_MS;
        if (!HQ_RTJoined() && next_snapshot > fallback_deadline) next_snapshot = fallback_deadline;
        xSemaphoreTake(guard, portMAX_DELAY);
        if (current_generation != generation) {
            xSemaphoreGive(guard); wipe_free(jwt); cJSON_Delete(cfg); HQ_RTStop(); continue;
        }
        bool snapshot_now = refresh_requested || now >= next_snapshot;
        refresh_requested = false;
        cJSON *sent = !snapshot_now ? cJSON_Duplicate(cJSON_GetArrayItem(outbox, 0), true) : NULL;
        char photo[sizeof photo_request] = {0};
        if (!snapshot_now && !sent && !photo_cache_clear_pending && photo_generation == current_generation) {
            snprintf(photo, sizeof photo, "%s", photo_request); photo_request[0] = 0;
        }
        xSemaphoreGive(guard);
        if (!jwt) { cJSON_Delete(sent); cJSON_Delete(cfg); continue; }
        if (*photo) {
            /* The sole worker lends its inactive HTTP slot as the 32 KiB PNG
             * dictionary. No HTTP call overlaps decoding, and canonical stays
             * untouched. Parking TLS leaves room for context and destination. */
            HQ_RTStop();
            char url[512];
            snprintf(url, sizeof url, "%s/storage/v1/object/authenticated/homehq-photos/%s", string_field(cfg, "url"), photo);
            bool photo_is_current = photo_current(&photo_context);
            if (photo_is_current) HQ_PhotoDownload(url, jwt, string_field(cfg, "key"), photo_context.user, photo_current, &photo_context,
                                                  (uint8_t *)http_scratch, RESPONSE_MAX + 1);
            xSemaphoreTake(guard, portMAX_DELAY);
            photo_is_current = current_generation == generation;
            if (photo_is_current) refresh_requested = true;
            xSemaphoreGive(guard);
            if (!photo_is_current) HQ_PhotoReset();
            wipe_free(jwt); cJSON_Delete(cfg); continue;
        }
        if (!snapshot_now && !sent) {
            wipe_free(jwt); cJSON_Delete(cfg); ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(100)); continue;
        }
        const char *path = "/rest/v1/rpc/homehq_snapshot";
        cJSON *body = snapshot_now ? cJSON_CreateObject() : rpc_body(sent, &path);
        int status;
        char *snapshot_wire = snapshot_now && body ? http_body(cfg, jwt, path, body, &status) : NULL;
        cJSON *reply = !snapshot_now && body ? http_json(cfg, jwt, path, body, &status) : NULL;
        if (!body) status = 0;
        cJSON_Delete(body); wipe_free(jwt); cJSON_Delete(cfg);
        bool success = status >= 200 && status < 300 && (snapshot_now ? snapshot_wire != NULL : reply != NULL);
        bool cache_saved = true;
        if (success && snapshot_now) {
            cache_saved = save_cache_candidate(snapshot_wire, current_generation);
            if (install_snapshot_wire(snapshot_wire, current_generation)) { snapshot_wire = NULL; next_snapshot = milliseconds() + (HQ_RTJoined() ? 60000 : SNAPSHOT_PERIOD_MS); }
            else success = false;
        } else if (success) {
            xSemaphoreTake(guard, portMAX_DELAY);
            if (current_generation == generation) success = acknowledge_locked(sent, reply);
            else success = false;
            xSemaphoreGive(guard);
        }
        if (success && snapshot_now) {
            xSemaphoreTake(guard, portMAX_DELAY);
            if (current_generation == generation) {
                if (!cache_saved && !strcmp(status_text, "Connected")) set_status("Connected. Cache full.");
                publish_locked();
            }
            xSemaphoreGive(guard);
        }
        if (!success) {
            if (status == 401) HQ_RTStop();
            xSemaphoreTake(guard, portMAX_DELAY);
            if (current_generation == generation) {
                if (status == 401) { replace_string(&access_token, NULL); set_status("Renewing session"); }
                else set_status(status == 403 ? "Home access unavailable" : status ? "Home unavailable. Retrying." : "Offline. Changes queued.");
                refresh_requested = snapshot_now;
            }
            xSemaphoreGive(guard);
            retry_at = milliseconds() + retry_ms;
            retry_ms = retry_ms < RETRY_MAX_MS / 2 ? retry_ms * 2 : RETRY_MAX_MS;
        } else { retry_at = 0; retry_ms = 1000; }
        if (snapshot_wire) memset(snapshot_wire, 0, strlen(snapshot_wire));
        cJSON_Delete(reply); cJSON_Delete(sent);
    }
}

void HQ_ServiceInit(void)
{
    if (guard) return;
    guard = xSemaphoreCreateMutex(); wifi_events = xEventGroupCreate();
    if (!guard || !wifi_events) return;
    if (!reserve_wire_buffers_locked()) set_status("Low memory. Retry.");
    store_ok = nvs_open("homehq", NVS_READWRITE, &store) == ESP_OK;
    restore_clock_locked();
    restore_photo_clear_locked();
    config = read_json("config", 4096);
    configured = cJSON_IsObject(config) && safe_url(string_field(config, "url")) && ordinary_key(string_field(config, "key")) && *string_field(config, "wifi_ssid") &&
        strlen(string_field(config, "wifi_ssid")) <= 32 && strlen(string_field(config, "wifi_password")) <= 63;
    if (!configured) { cJSON_Delete(config); config = NULL; }
    outbox = cJSON_CreateArray();
    replace_base_wire_locked(configured ? empty_wire : homehq_demo_json);
    cJSON *record = read_json("session", 2048);
    if (configured && cJSON_IsObject(record) && *string_field(record, "user_id") && strlen(string_field(record, "user_id")) <= 80 &&
        *string_field(record, "refresh_token") && strlen(string_field(record, "refresh_token")) <= 1024) {
        replace_string(&user_id, string_field(record, "user_id"));
        replace_string(&refresh_token, string_field(record, "refresh_token"));
        session_durable = user_id && refresh_token;
        char *cache = load_cache_locked();
        if (cache) { replace_base_wire_locked(cache); free(cache); }
        cJSON *saved = read_json("outbox", 14336);
        if (saved && text_equal(saved, "user_id", user_id)) {
            cJSON *command;
            cJSON_ArrayForEach(command, field(saved, "pending")) if (cJSON_GetArraySize(outbox) < OUTBOX_MAX && valid_command(command)) {
                cJSON_AddItemToArray(outbox, cJSON_Duplicate(command, true));
                const cJSON *seq = field(command, "sequence");
                if (cJSON_IsNumber(seq) && seq->valuedouble > next_sequence) next_sequence = (unsigned)seq->valuedouble;
            }
        }
        cJSON_Delete(saved);
    }
    cJSON_Delete(record);
    set_status(!configured ? "Demo" : refresh_token ? "Connecting" : "Sign in to your home");
    publish_locked(); refresh_requested = configured;
    if (xTaskCreate(service_worker, "homehq_net", 8192, NULL, 3, &worker) != pdPASS) { worker = NULL; set_status("Network unavailable"); }
}
char *HQ_ServicePollWire(void)
{
    return HQ_ServicePollViewWire("today");
}
char *HQ_ServicePollViewWire(const char *page)
{
    if (!page) return NULL;
    if (!guard || xSemaphoreTake(guard, 0) != pdTRUE) return NULL;
    char *wire = delivery_dirty && base_wire ? HQ_ProjectCopy(base_wire, strlen(base_wire), page) : NULL;
    /* A failed allocation leaves the update pending; the old UI remains
     * authoritative until a complete replacement can be constructed. */
    if (wire) delivery_dirty = false;
    xSemaphoreGive(guard); return wire;
}
char *HQ_ServiceViewWire(const char *page)
{
    if (!guard || !page) return NULL;
    xSemaphoreTake(guard, portMAX_DELAY);
    /* A hosted canonical snapshot is ~25 KiB. Allocate only the requested
     * page's bytes so a page turn can fit beside a joined TLS connection.
     * The two projection passes require the canonical source to stay stable. */
    char *wire = base_wire ? HQ_ProjectCopy(base_wire, strlen(base_wire), page) : NULL;
    xSemaphoreGive(guard);
    return wire;
}
void HQ_ServiceOverlay(cJSON *ui_graph)
{
    if (!guard || !ui_graph) return;
    xSemaphoreTake(guard, portMAX_DELAY);
    const cJSON *command;
    cJSON_ArrayForEach(command, outbox) apply(ui_graph, command);
    xSemaphoreGive(guard);
}
/* Legacy callers receive Today projection. Native LVGL asks for its current
 * page and releases its previous graph before parsing the replacement. */
cJSON *HQ_ServicePoll(void)
{
    char *wire = HQ_ServicePollWire();
    cJSON *value = wire ? cJSON_Parse(wire) : NULL;
    free(wire); HQ_ServiceOverlay(value); return value;
}
void HQ_ServiceStatus(char *buffer, unsigned capacity, unsigned *pending)
{
    if (!guard) { if (capacity) snprintf(buffer, capacity, "Starting"); if (pending) *pending = 0; return; }
    xSemaphoreTake(guard, portMAX_DELAY);
    if (capacity) snprintf(buffer, capacity, "%s", status_text);
    if (pending) *pending = (unsigned)cJSON_GetArraySize(outbox);
    xSemaphoreGive(guard);
}
void HQ_ServiceDiagnostics(HQ_ServiceDiagnosticsInfo *result)
{
    if (!result) return;
    memset(result, 0, sizeof *result);
    if (!guard) return;
    xSemaphoreTake(guard, portMAX_DELAY);
    result->configured = configured;
    result->authenticated = access_token && session_durable;
    result->session_saved = session_durable;
    result->wifi_enabled = wifi_enabled;
    result->wifi_connected = wifi_events && (xEventGroupGetBits(wifi_events) & WIFI_CONNECTED);
    result->wifi_disconnect_reason = latest_wifi_disconnect_reason;
    result->radio_paused = radio_paused;
    result->clock_ready = clock_valid((uint64_t)time(NULL));
    result->realtime_joined = HQ_RTJoined();
    result->pending = cJSON_GetArraySize(outbox);
    result->revision = base_info.revision >= 0 && (uint64_t)base_info.revision <= UINT32_MAX ? (unsigned)base_info.revision : 0;
    xSemaphoreGive(guard);
}
bool HQ_ServiceSetClock(uint64_t epoch)
{
    if (!guard || !clock_valid(epoch) || !apply_clock(epoch)) return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    /* A USB clock is trusted setup input. Checkpoint only our namespace and
     * retain it on logout, so lack of a battery RTC never weakens TLS checks. */
    bool ok = save_clock_locked(epoch, true);
    xSemaphoreGive(guard); wake_worker(); return ok;
}
bool HQ_ServiceRadio(bool enabled)
{
    if (!guard) return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    radio_paused = !enabled;
    wifi_enabled = enabled && wifi_initialized && configured;
    bool initialized = wifi_initialized, connect = wifi_enabled;
    if (!enabled && wifi_events) xEventGroupClearBits(wifi_events, WIFI_CONNECTED);
    refresh_requested = enabled;
    if (!enabled) set_status("Radio paused. Changes queued.");
    xSemaphoreGive(guard);
    /* This recovery control is transient: it never alters saved credentials or
     * other devices. The pause flag suppresses the normal disconnect reconnect. */
    if (initialized) { if (connect) esp_wifi_connect(); else if (!enabled) esp_wifi_disconnect(); }
    wake_worker(); return true;
}
bool HQ_ServiceCommand(const cJSON *command)
{
    if (!guard || !valid_command(command)) return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    if ((configured && (!user_id || !refresh_token || !session_durable || logout_intent || configuration_intent))) {
        set_status("Sign in to your home"); xSemaphoreGive(guard); return false;
    }
    cJSON *queued = bounded_command(command);
    if (!queued) { set_status("Low memory. Retry."); xSemaphoreGive(guard); return false; }
    cJSON_AddNumberToObject(queued, "sequence", ++next_sequence);
    if (!configured) {
        cJSON_Delete(queued); set_status("Demo. Local changes.");
        xSemaphoreGive(guard); return true;
    }
    cJSON *old_queue = cJSON_Duplicate(outbox, true);
    if (!old_queue) { cJSON_Delete(queued); xSemaphoreGive(guard); return false; }
    int replace = -1;
    for (int i = 0; i < cJSON_GetArraySize(outbox); ++i) {
        cJSON *old = cJSON_GetArrayItem(outbox, i);
        if (text_equal(old, "kind", string_field(queued, "kind")) && text_equal(old, "id", string_field(queued, "id"))) {
            /* Offline presses coalesce to an absolute desired value while the
             * first observed version remains the conflict detection baseline. */
            set_copy(queued, "version", field(old, "version")); replace = i; break;
        }
    }
    if (replace < 0 && cJSON_GetArraySize(outbox) >= OUTBOX_MAX) {
        cJSON_Delete(queued); cJSON_Delete(old_queue); set_status("Queue full. Connect to save."); xSemaphoreGive(guard); return false;
    }
    if (replace >= 0) cJSON_ReplaceItemInArray(outbox, replace, queued); else cJSON_AddItemToArray(outbox, queued);
    bool ok = save_outbox_locked();
    if (!ok) { cJSON_Delete(outbox); outbox = old_queue; set_status("Changes not saved. Free storage."); }
    else { cJSON_Delete(old_queue); set_status("Changes queued"); }
    xSemaphoreGive(guard); if (ok) wake_worker();
    return ok;
}
/* USB provisioning copies {wifi_ssid,wifi_password,url,key,email,password};
 * only the first four are configuration. On-device sign-in reuses those via
 * HQ_ServiceSignIn, so passwords never become a saved configuration field. */
bool HQ_ServiceConfigure(const cJSON *configuration)
{
    if (!guard || !cJSON_IsObject(configuration)) return false;
    const char *ssid = string_field(configuration, "wifi_ssid"), *wifi_password = string_field(configuration, "wifi_password");
    const char *url = string_field(configuration, "url"), *key = string_field(configuration, "key");
    const char *email = string_field(configuration, "email"), *password = string_field(configuration, "password");
    if (!*ssid || strlen(ssid) > 32 || strlen(wifi_password) > 63 || !safe_url(url) || !ordinary_key(key) ||
        !*email || strlen(email) > 320 || !*password || strlen(password) > 512) return false;
    cJSON *public = cJSON_CreateObject(), *intent = cJSON_CreateObject();
    if (!public || !intent) { cJSON_Delete(public); cJSON_Delete(intent); return false; }
    cJSON_AddStringToObject(public, "wifi_ssid", ssid); cJSON_AddStringToObject(public, "wifi_password", wifi_password);
    cJSON_AddStringToObject(public, "url", url); cJSON_AddStringToObject(public, "key", key);
    cJSON_AddStringToObject(intent, "email", email); cJSON_AddStringToObject(intent, "password", password);
    xSemaphoreTake(guard, portMAX_DELAY);
    bool ok = !cJSON_GetArraySize(outbox) && !configuration_intent && !logout_intent;
    if (!ok) set_status("Connect to save changes first.");
    if (ok) {
        ok = clear_identity_locked();
        if (ok) {
            ++generation;
            replace_base_wire_locked(empty_wire); publish_locked();
            ok = save_json("config", public);
            if (!ok) set_status("Setup not saved. Free storage.");
        }
    }
    if (ok) {
        configured = true;
        cJSON_Delete(config); config = public; public = NULL;
        configuration_intent = intent; intent = NULL;
        set_status("Signing in"); refresh_requested = true;
    }
    xSemaphoreGive(guard);
    cJSON_Delete(public); scrub_login(intent); if (ok) wake_worker();
    return ok;
}
bool HQ_ServiceLogout(void)
{
    if (!guard) return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    if (cJSON_GetArraySize(outbox)) { set_status("Connect to save changes first."); xSemaphoreGive(guard); return false; }
    cJSON *credentials = cJSON_CreateObject();
    if (credentials) {
        if (access_token) cJSON_AddStringToObject(credentials, "access_token", access_token);
        if (refresh_token) cJSON_AddStringToObject(credentials, "refresh_token", refresh_token);
    }
    bool ok = clear_identity_locked();
    if (ok) {
        cJSON_Delete(logout_credentials); logout_credentials = credentials; credentials = NULL;
        ++generation; scrub_login(configuration_intent); configuration_intent = NULL;
        logout_intent = true; configured = false; HQ_PhotoReset();
        replace_base_wire_locked(homehq_demo_json); publish_locked(); set_status("Demo. Signed out.");
    }
    xSemaphoreGive(guard);
    if (credentials) {
        cJSON *v = cJSON_GetObjectItemCaseSensitive(credentials, "access_token"); if (cJSON_IsString(v)) memset(v->valuestring, 0, strlen(v->valuestring));
        v = cJSON_GetObjectItemCaseSensitive(credentials, "refresh_token"); if (cJSON_IsString(v)) memset(v->valuestring, 0, strlen(v->valuestring));
        cJSON_Delete(credentials);
    }
    if (ok) wake_worker();
    return ok;
}
void HQ_ServiceRefresh(void)
{
    if (!guard) return;
    xSemaphoreTake(guard, portMAX_DELAY); refresh_requested = true; xSemaphoreGive(guard); wake_worker();
}
bool HQ_ServicePhotoRequest(const char *path)
{
    if (!guard || !path || !*path || strlen(path) >= sizeof photo_request) return false;
    xSemaphoreTake(guard, portMAX_DELAY);
    const char *home = base_info.home; size_t n = strlen(home), length = strlen(path);
    bool ok = configured && user_id && n && !strncmp(path, home, n) && path[n] == '/' && length > n + 5 &&
              !strcmp(path + length - 4, ".png") && !strstr(path, "..");
    for (const char *p = path; ok && *p; ++p) if (!(isalnum((unsigned char)*p) || *p == '-' || *p == '_' || *p == '/' || *p == '.')) ok = false;
    if (ok) { snprintf(photo_request, sizeof photo_request, "%s", path); photo_generation = generation; }
    xSemaphoreGive(guard); if (ok) wake_worker();
    return ok;
}

bool HQ_ServiceSignIn(const char *email, const char *password)
{
    if (!guard || !email || !password || !*email || !*password || strlen(email) > 320 || strlen(password) > 512) return false;
    cJSON *intent = cJSON_CreateObject();
    if (!intent) return false;
    cJSON_AddStringToObject(intent, "email", email); cJSON_AddStringToObject(intent, "password", password);
    xSemaphoreTake(guard, portMAX_DELAY);
    bool ok = config && !configuration_intent && !logout_intent;
    if (ok && !cJSON_GetArraySize(outbox)) {
        ok = clear_identity_locked();
        if (ok) { replace_base_wire_locked(empty_wire); publish_locked(); HQ_PhotoReset(); }
    }
    /* A lost refresh session can still have durable offline writes. Preserve
     * those and require the password response's user id to match their owner;
     * attempting another account cannot discard or inherit the outbox. */
    if (ok) {
        ++generation; configured = true;
        configuration_intent = intent; intent = NULL;
        photo_request[0] = 0; set_status("Signing in");
    } else if (!config) set_status("Set up Wi-Fi and project first");
    xSemaphoreGive(guard);
    scrub_login(intent); if (ok) wake_worker();
    return ok;
}
