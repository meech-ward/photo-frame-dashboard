#pragma once
/* Host checks execute the real state machine with an in-memory NVS boundary.
 * No test has network, radio, device or credential access. */
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM 1
#define ESP_ERR_INVALID_STATE 2
#define ESP_ERR_NVS_NOT_FOUND 3
#define BIT0 1
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define portMAX_DELAY 0xffffffffu
#define pdMS_TO_TICKS(x) (x)
typedef void *SemaphoreHandle_t;
typedef void *EventGroupHandle_t;
typedef void *TaskHandle_t;
static int fake_busy, fake_nvs_failure;
static int64_t fake_time_ms = 100000;
static inline int64_t esp_timer_get_time(void) { return fake_time_ms * 1000; }
static inline void *xSemaphoreCreateMutex(void) { return (void *)1; }
static inline void *xEventGroupCreate(void) { return (void *)1; }
static inline int xSemaphoreTake(void *p, unsigned wait) { (void)p; return !wait && fake_busy ? 0 : 1; }
static inline int xSemaphoreGive(void *p) { (void)p; return 1; }
static inline unsigned xEventGroupGetBits(void *p) { (void)p; return 0; }
static inline void xEventGroupSetBits(void *p, unsigned b) { (void)p; (void)b; }
static inline void xEventGroupClearBits(void *p, unsigned b) { (void)p; (void)b; }
static inline int xTaskCreate(void (*f)(void *), const char *name, unsigned stack, void *arg, int priority, void **handle) { (void)f; (void)name; (void)stack; (void)arg; (void)priority; *handle = (void *)1; return 1; }
static inline void xTaskNotifyGive(void *p) { (void)p; }
static inline unsigned ulTaskNotifyTake(int clear, unsigned wait) { (void)clear; (void)wait; return 0; }
typedef int nvs_handle_t;
#define NVS_READWRITE 1
typedef struct { char key[20]; unsigned char *data; size_t length; } fake_nvs_entry;
static fake_nvs_entry fake_nvs[16];
static inline fake_nvs_entry *fake_entry(const char *key, int create) {
    for (unsigned i=0;i<16;i++) if (!strcmp(fake_nvs[i].key,key)) return &fake_nvs[i];
    if (create) for (unsigned i=0;i<16;i++) if (!*fake_nvs[i].key) { snprintf(fake_nvs[i].key,sizeof fake_nvs[i].key,"%s",key); return &fake_nvs[i]; }
    return NULL;
}
static inline int nvs_open(const char *name, int mode, int *handle) { (void)name; (void)mode; *handle=1; return 0; }
static inline int nvs_set_blob(int handle,const char *key,const void *value,size_t n) {
    (void)handle; if(fake_nvs_failure)return 1; fake_nvs_entry *e=fake_entry(key,1); if(!e)return 1;
    unsigned char *copy=malloc(n); if(!copy)return 1; memcpy(copy,value,n); free(e->data); e->data=copy; e->length=n; return 0;
}
static inline int nvs_set_str(int h,const char *key,const char *s) { return nvs_set_blob(h,key,s,strlen(s)+1); }
static inline int nvs_get_blob(int h,const char *key,void *buffer,size_t *n) {
    (void)h; fake_nvs_entry *e=fake_entry(key,0); if(!e)return ESP_ERR_NVS_NOT_FOUND;
    if(!buffer){*n=e->length;return 0;}if(*n<e->length)return 1;memcpy(buffer,e->data,e->length);*n=e->length;return 0;
}
static inline int nvs_get_str(int h,const char *key,char *buffer,size_t *n) { return nvs_get_blob(h,key,buffer,n); }
static inline int nvs_erase_key(int h,const char *key) { (void)h;if(fake_nvs_failure)return 1;fake_nvs_entry *e=fake_entry(key,0);if(!e)return ESP_ERR_NVS_NOT_FOUND;free(e->data);memset(e,0,sizeof *e);return 0; }
static inline int nvs_commit(int h) { (void)h;return fake_nvs_failure?1:0; }
typedef struct { int event_id,data_len;void *data,*user_data; } esp_http_client_event_t;
#define HTTP_EVENT_ON_DATA 1
#define HTTP_METHOD_POST 1
typedef void *esp_http_client_handle_t;
typedef struct { const char *url;int method,timeout_ms;esp_err_t(*event_handler)(esp_http_client_event_t*);void *user_data;void(*crt_bundle_attach)(void);int disable_auto_redirect,buffer_size,buffer_size_tx; } esp_http_client_config_t;
static inline void esp_crt_bundle_attach(void) {}
static inline void *esp_http_client_init(const esp_http_client_config_t *c) { (void)c;return NULL; }
static inline int esp_http_client_set_header(void *h,const char *k,const char *v) { (void)h;(void)k;(void)v;return 0; }
static inline int esp_http_client_set_post_field(void *h,const char *v,int n) { (void)h;(void)v;(void)n;return 0; }
static inline int esp_http_client_perform(void *h) { (void)h;return 1; }
static inline int esp_http_client_get_status_code(void *h) { (void)h;return 0; }
static inline void esp_http_client_cleanup(void *h) { (void)h; }
typedef int esp_event_base_t;
#define IP_EVENT 1
#define WIFI_EVENT 2
#define IP_EVENT_STA_GOT_IP 3
#define WIFI_EVENT_STA_DISCONNECTED 4
#define WIFI_EVENT_STA_START 5
#define ESP_EVENT_ANY_ID -1
#define WIFI_STORAGE_RAM 0
#define WIFI_MODE_STA 0
#define WIFI_IF_STA 0
#define WIFI_PS_NONE 0
typedef struct { int unused; } wifi_init_config_t;
#define WIFI_INIT_CONFIG_DEFAULT() ((wifi_init_config_t){0})
typedef struct { struct { unsigned char ssid[32],password[64]; } sta; } wifi_config_t;
static inline int esp_wifi_connect(void) { return 0; }
static inline int esp_wifi_stop(void) { return 0; }
static inline int esp_wifi_start(void) { return 0; }
static inline int esp_netif_init(void) { return 0; }
static inline int esp_event_loop_create_default(void) { return 0; }
static inline void *esp_netif_create_default_wifi_sta(void) { return (void *)1; }
static inline int esp_wifi_init(const wifi_init_config_t *c) { (void)c;return 0; }
static inline int esp_wifi_set_storage(int x) { (void)x;return 0; }
static inline int esp_wifi_set_mode(int x) { (void)x;return 0; }
static inline int esp_wifi_set_ps(int x) { (void)x;return 0; }
static inline int esp_wifi_set_config(int x,const wifi_config_t *c) { (void)x;(void)c;return 0; }
static inline int esp_event_handler_register(int event,int id,void(*f)(void*,int,int32_t,void*),void *arg) { (void)event;(void)id;(void)f;(void)arg;return 0; }
typedef struct { const char *server; } esp_sntp_config_t;
#define ESP_NETIF_SNTP_DEFAULT_CONFIG(s) ((esp_sntp_config_t){s})
static inline int esp_netif_sntp_init(const esp_sntp_config_t *s) { (void)s;return 0; }
static inline int mbedtls_base64_decode(unsigned char *dst,size_t cap,size_t *n,const unsigned char *src,size_t len) { (void)dst;(void)cap;(void)n;(void)src;(void)len;return 1; }
