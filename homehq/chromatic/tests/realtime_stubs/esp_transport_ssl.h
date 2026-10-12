#pragma once
#include "esp_transport.h"
void *esp_transport_ssl_init(void);
void esp_transport_ssl_crt_bundle_attach(void *,int (*)(void *));
