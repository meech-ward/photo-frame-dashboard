#include "homehq.h"
#include "homehq_console.h"
#include "esp_console.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "mbedtls/base64.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
#include <ctype.h>
static QueueHandle_t inputs;
typedef struct {uint8_t kind;char key[8];} ConsoleInput;
enum {INPUT_BUTTON, INPUT_VIEW};
static char provisioning[4096];
static size_t used;
static int command(int argc, char **argv)
{
    if (argc<2) return 1;
    if (!strcmp(argv[1], "status")) {
        char state[48]; unsigned pending=0;
        HQ_ServiceStatus(state,sizeof(state),&pending);
        printf("HQ state=%s pending=%u heap=%u largest=%u\n",state,pending,
               (unsigned)esp_get_free_heap_size(),
               (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
        return 0;
    }
    if (!strcmp(argv[1], "diagnostics") && argc == 2) {
        HQ_ServiceDiagnosticsInfo result;
        HQ_ServiceDiagnostics(&result);
        /* Fixed scalars cannot echo credentials or provider text. Keep the raw
         * disconnect reason: absence of an AP does not diagnose its password. */
        printf("HQ diagnostics configured=%u authenticated=%u session_saved=%u pending=%u revision=%u radio_paused=%u clock_ready=%u realtime_joined=%u\n",
            (unsigned)result.configured, (unsigned)result.authenticated, (unsigned)result.session_saved, result.pending, result.revision,
            (unsigned)result.radio_paused, (unsigned)result.clock_ready, (unsigned)result.realtime_joined);
        printf("HQ wifi enabled=%u connected=%u reason=%u\n",
            (unsigned)result.wifi_enabled, (unsigned)result.wifi_connected, result.wifi_disconnect_reason);
        HQ_PhotoDiagnosticsInfo photo; HQ_PhotoDiagnostics(&photo);
        printf("HQ photo download_ok=%u download_failed=%u stage=%u http_status=%u cache_hits=%u cache_misses=%u cache_saved=%u cache_save_failed=%u cache_clear_failed=%u tls_error=%d transport_error=%d\n",
            photo.download_ok,photo.download_failed,photo.stage,photo.http_status,
            photo.cache_hits,photo.cache_misses,photo.cache_saved,photo.cache_save_failed,photo.cache_clear_failed,photo.tls_error,photo.transport_error);
        return 0;
    }
    if (!strcmp(argv[1], "clock") && argc == 3) {
        bool numeric = *argv[2] != 0;
        for (const char *p = argv[2]; *p; ++p) if (!isdigit((unsigned char)*p)) numeric = false;
        char *end = NULL; errno = 0;
        unsigned long long epoch = numeric ? strtoull(argv[2], &end, 10) : 0;
        bool ok = numeric && !errno && end && !*end && HQ_ServiceSetClock((uint64_t)epoch);
        printf("HQ clock=%s\n", ok ? "accepted" : "rejected"); return ok ? 0 : 1;
    }
    if (!strcmp(argv[1], "radio") && argc == 3) {
        bool enabled = !strcmp(argv[2], "on");
        bool ok = (enabled || !strcmp(argv[2], "off")) && HQ_ServiceRadio(enabled);
        printf("HQ radio=%s\n", ok ? (enabled ? "on" : "off") : "rejected"); return ok ? 0 : 1;
    }
    if (!strcmp(argv[1],"view") && argc==2) {
        ConsoleInput input={.kind=INPUT_VIEW};
        return inputs && xQueueSend(inputs,&input,0)==pdTRUE ? 0 : 1;
    }
    if (!strcmp(argv[1],"input") && argc==3) {
        const char *valid[]={"left","right","up","down","a","b","start","select"};
        for (unsigned i=0;i<8;i++) if (!strcmp(argv[2],valid[i])) {
            ConsoleInput input={.kind=INPUT_BUTTON};snprintf(input.key,sizeof(input.key),"%s",valid[i]);
            return inputs && xQueueSend(inputs,&input,0)==pdTRUE ? 0 : 1;
        }
        return 1;
    }
    if (!strcmp(argv[1],"refresh")) {HQ_ServiceRefresh(); return 0;}
    /* Chunking avoids the observed UART loss on console lines above 96 bytes.
     * Never print assembled credentials, decoded JSON or Auth replies. */
    if (!strcmp(argv[1],"config-begin")) {memset(provisioning,0,sizeof(provisioning));used=0;return 0;}
    if (!strcmp(argv[1],"config-part") && argc==3) {
        size_t n=strlen(argv[2]);
        if (n>64 || used+n>=sizeof(provisioning)) return 1;
        memcpy(provisioning+used,argv[2],n);used+=n;return 0;
    }
    if (!strcmp(argv[1],"config-save")) {
        unsigned char *decoded=calloc(1,3073);size_t n=0;
        bool ok=decoded && !mbedtls_base64_decode(decoded,3072,&n,(unsigned char*)provisioning,used);
        cJSON *config=ok ? cJSON_ParseWithLength((char*)decoded,n+1) : NULL;
        ok=config && HQ_ServiceConfigure(config);
        cJSON_Delete(config);
        if(decoded){memset(decoded,0,3073);free(decoded);}
        memset(provisioning,0,sizeof(provisioning));used=0;
        printf("HQ provision=%s\n",ok?"queued":"rejected");return ok?0:1;
    }
    return 1;
}
void HQ_ConsoleInit(void)
{
    inputs=xQueueCreate(16,sizeof(ConsoleInput));
    esp_console_cmd_t cmd={.command="hq",.help="Home HQ status/diagnostics/clock/radio/view/input/refresh; private chunked config",.func=command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&cmd));
}
static const char *string_field(const cJSON *object,const char *key)
{
    const cJSON *value=cJSON_GetObjectItemCaseSensitive(object,key);
    return cJSON_IsString(value)?value->valuestring:"";
}
static void label_safe(const char *source,char *output,size_t capacity)
{
    size_t length=0;
    while(*source && length+1<capacity) {
        unsigned char c=(unsigned char)*source++;
        output[length++]=(c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.'?(char)c:'_';
    }
    output[length]=0;
}
static void print_buttons(void)
{
    /* Physical counters are owned by LVGL. The API adds a fixed field set and
     * a known page key; no typed text or credential storage enters this JSON. */
    cJSON *object = cJSON_CreateObject();
    if (!object) { printf("HQ buttons unavailable\n"); return; }
    HomeHQ_InputDiagnostics(object);
    char *wire = cJSON_PrintUnformatted(object);
    if (wire) { printf("HQ buttons %s\n", wire); free(wire); }
    else printf("HQ buttons unavailable\n");
    cJSON_Delete(object);
}
static void print_view(void)
{
    /* The graph can be replaced and freed during LVGL maintain. Queue this
     * read alongside button actions instead of dereferencing it on core 0.
     * A person's display label is enough for diagnostics: never print an Auth
     * UUID, email, password, JWT, provider response or a private photo path. */
    const cJSON *snapshot=HomeHQ_Data();
    const cJSON *viewer=cJSON_GetObjectItemCaseSensitive(snapshot,"viewer");
    const char *person_id=string_field(viewer,"person_id"),*name="none";
    const cJSON *people=cJSON_GetObjectItemCaseSensitive(snapshot,"people"),*person;
    cJSON_ArrayForEach(person,people) {
        if(*person_id&&!strcmp(person_id,string_field(person,"id"))) {name=string_field(person,"name");break;}
    }
    char safe_name[49];label_safe(*name?name:"none",safe_name,sizeof(safe_name));
    const cJSON *value=cJSON_GetObjectItemCaseSensitive(snapshot,"revision");
    unsigned revision=cJSON_IsNumber(value)&&value->valuedouble>=0&&value->valuedouble<=UINT_MAX?(unsigned)value->valuedouble:0;
    const char *detail=HomeHQ_Detail();
    printf("HQ view page=%s detail=%s focus=%d revision=%u viewer=%s minheap=%u\n",
           HomeHQ_Page(),*detail?detail:"none",HomeHQ_Focus(),revision,safe_name,
           (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT));
}
void HQ_ConsolePoll(void)
{
    /* Serial callbacks run on another core. Widgets and their model remain
     * owned by the LVGL task, including diagnostic replay of physical actions. */
    ConsoleInput input;
    while(inputs && xQueueReceive(inputs,&input,0)==pdTRUE) {
        if(input.kind==INPUT_VIEW){print_view();print_buttons();}
        else if(input.kind==INPUT_BUTTON)HomeHQ_Input(input.key);
    }
}
