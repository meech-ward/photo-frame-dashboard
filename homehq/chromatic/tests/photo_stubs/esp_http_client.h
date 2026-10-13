#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef int esp_err_t;
#define ESP_OK 0
typedef struct mock_http *esp_http_client_handle_t;
enum {HTTP_EVENT_ERROR, HTTP_EVENT_DISCONNECTED, HTTP_EVENT_ON_HEADER};
typedef struct {int event_id; void *data, *user_data; const char *header_key, *header_value;} esp_http_client_event_t;
typedef struct {
    const char *url;
    int timeout_ms, buffer_size, buffer_size_tx;
    esp_err_t (*crt_bundle_attach)(void *configuration);
    esp_err_t (*event_handler)(esp_http_client_event_t *event);
    void *user_data;
    bool disable_auto_redirect, keep_alive_enable;
} esp_http_client_config_t;
esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *configuration);
esp_err_t esp_http_client_set_header(esp_http_client_handle_t client, const char *key, const char *value);
esp_err_t esp_http_client_open(esp_http_client_handle_t client, int length);
int64_t esp_http_client_fetch_headers(esp_http_client_handle_t client);
int esp_http_client_get_status_code(esp_http_client_handle_t client);
int esp_http_client_read(esp_http_client_handle_t client, char *bytes, int length);
bool esp_http_client_is_complete_data_received(esp_http_client_handle_t client);
esp_err_t esp_http_client_close(esp_http_client_handle_t client);
esp_err_t esp_http_client_cleanup(esp_http_client_handle_t client);
