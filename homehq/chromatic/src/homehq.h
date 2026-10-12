#pragma once
#include <stdbool.h>
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
extern const char homehq_demo_json[];

void HQ_ServiceInit(void);
/* Caller owns and must delete the returned snapshot; NULL means no change. */
cJSON *HQ_ServicePoll(void);
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
void HQ_PhotoMaintain(const cJSON *photo);
bool HQ_PhotoChanged(void);
bool HQ_PhotoDownload(const char *url, const char *bearer, const char *apikey);
void HQ_PhotoReset(void);
bool HQ_ServicePhotoRequest(const char *path);
