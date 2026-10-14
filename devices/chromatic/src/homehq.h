#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "lvgl.h"
#include "cJSON.h"

/* Only the LVGL task owns the view and its snapshot. Network workers transfer
 * complete graphs; they never mutate widgets or the graph being rendered. */
void HomeHQ_Show(lv_obj_t *screen);
void HomeHQ_Maintain(void);
void HomeHQ_Input(const char *button);
const char *HomeHQ_Page(void);
const char *HomeHQ_Detail(void);
int HomeHQ_Focus(void);
const cJSON *HomeHQ_Data(void);
/* Called from the LVGL task; scalar diagnostics never include typed values. */
void HomeHQ_InputDiagnostics(cJSON *object);
extern const char homehq_demo_json[];

void HQ_ServiceInit(void);
/* Caller owns and must delete the returned snapshot; NULL means no change. */
cJSON *HQ_ServicePoll(void);
/* Owned wire text keeps the service from retaining a second full cJSON graph.
 * UI frees its old graph before decoding this transfer, then applies outbox. */
/* Legacy Today alias; native UI requests its current page to bound memory. */
char *HQ_ServicePollWire(void);
char *HQ_ServicePollViewWire(const char *page);
char *HQ_ServiceViewWire(const char *page);
void HQ_ServiceOverlay(cJSON *ui_graph);
bool HQ_ServiceCommand(const cJSON *command);
void HQ_ServiceStatus(char *buffer, unsigned capacity, unsigned *pending);
/* Provisioning copies input and never logs credentials. Password is transient;
 * refresh token, Wi-Fi and public project configuration live in separate NVS. */
bool HQ_ServiceConfigure(const cJSON *configuration);
bool HQ_ServiceSignIn(const char *email, const char *password);
bool HQ_ServiceLogout(void);
void HQ_ServiceRefresh(void);

/* Photo pixels are transferred at display resolution to avoid retaining a
 * 307,200-byte decoded badge image on the ESP32 without external RAM. */
const lv_img_dsc_t *HQ_Photo(const cJSON *photo);
bool HQ_PhotoIsFallback(const cJSON *photo);
/* LVGL only, after deleting old image widgets; preserve a matching mailbox. */
void HQ_PhotoRetireUnused(const cJSON *photo);
void HQ_PhotoMaintain(const cJSON *photo);
bool HQ_PhotoChanged(void);
bool HQ_PhotoWorkerBusy(void);
typedef bool (*HQ_PhotoGuard)(void *context);
typedef struct {
    unsigned download_ok, download_failed, stage, http_status;
    unsigned cache_hits, cache_misses, cache_saved, cache_save_failed, cache_clear_failed;
    int tls_error, transport_error;
} HQ_PhotoDiagnosticsInfo;
void HQ_PhotoDiagnostics(HQ_PhotoDiagnosticsInfo *result);
bool HQ_PhotoClearCache(void);
bool HQ_PhotoRestore(const char *user, const char *path, HQ_PhotoGuard guard, void *context);
bool HQ_PhotoDownload(const char *url, const char *bearer, const char *apikey,
                      const char *user, HQ_PhotoGuard guard, void *context,
                      uint8_t *dictionary, size_t dictionary_capacity);
void HQ_PhotoReset(void);
bool HQ_ServicePhotoRequest(const char *path);

/* Safe scalar diagnostics deliberately exclude network and account identifiers. */
typedef struct {
    bool configured, authenticated, session_saved, wifi_enabled, wifi_connected, radio_paused, clock_ready, realtime_joined;
    unsigned wifi_disconnect_reason, pending, revision;
} HQ_ServiceDiagnosticsInfo;
void HQ_ServiceDiagnostics(HQ_ServiceDiagnosticsInfo *result);

bool HQ_ServiceSetClock(uint64_t epoch);
bool HQ_ServiceRadio(bool enabled);
