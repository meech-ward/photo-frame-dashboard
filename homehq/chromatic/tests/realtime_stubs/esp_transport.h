#pragma once
#include <stdbool.h>
#include <stddef.h>
typedef void *esp_transport_handle_t;
typedef int esp_err_t;
#define ESP_OK 0
int esp_transport_close(void *);
int esp_transport_destroy(void *);
int esp_transport_connect(void *,const char *,int,int);
int esp_transport_read(void *,char *,int,int);
