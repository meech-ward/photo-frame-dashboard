#pragma once
typedef void *esp_tls_error_handle_t;
int esp_tls_get_and_clear_last_error(esp_tls_error_handle_t, int *, int *);
