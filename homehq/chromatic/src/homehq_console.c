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
static QueueHandle_t inputs;
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
    if (!strcmp(argv[1],"input") && argc==3) {
        const char *valid[]={"left","right","up","down","a","b","start","select"};
        for (unsigned i=0;i<8;i++) if (!strcmp(argv[2],valid[i])) {
            char key[8]={0}; snprintf(key,sizeof(key),"%s",valid[i]);
            return xQueueSend(inputs,key,0)==pdTRUE ? 0 : 1;
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
    inputs=xQueueCreate(16,8);
    esp_console_cmd_t cmd={.command="hq",.help="Home HQ status/input/refresh; private chunked config",.func=command};
    ESP_ERROR_CHECK(esp_console_cmd_register(&cmd));
}
void HQ_ConsolePoll(void)
{
    /* Serial callbacks run on another core. Widgets and their model remain
     * owned by the LVGL task, including diagnostic replay of physical actions. */
    char key[8];
    while(inputs && xQueueReceive(inputs,key,0)==pdTRUE) HomeHQ_Input(key);
}
