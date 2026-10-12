#include "homehq.h"
#include "homehq_realtime.h"
#include "esp_transport.h"
#include "esp_transport_ssl.h"
#include "esp_transport_ws.h"
#include "esp_crt_bundle.h"
#include "esp_timer.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#define MESSAGE_MAX 8192
static esp_transport_handle_t ssl, socket;
static char *project_url, *public_key, *household, *token;
static char message[MESSAGE_MAX+1];
static unsigned used, frame_left, reference, heartbeat_ref;
static unsigned frame_opcode, control_used;
static char control[125];
static bool frame_fin, fragmented, joined, awaiting_heartbeat;
static int64_t retry_at, heartbeat_at, acknowledgement_until, join_until;
static unsigned retry_ms=1000;
static int64_t now_ms(void) {return esp_timer_get_time()/1000;}
static const char *str(const cJSON *o,const char *key)
{
    const cJSON *v=cJSON_GetObjectItemCaseSensitive(o,key);
    return cJSON_IsString(v)?v->valuestring:"";
}
static void wipe(char **p)
{
    if(*p){volatile char *s=*p;size_t n=strlen(*p);while(n--)*s++=0;free(*p);*p=NULL;}
}
static void disconnect(void)
{
    /* WS wraps SSL without owning it: close the connection once, then destroy
     * both handles. An orphaned TLS session would consume the photo budget. */
    if(socket){esp_transport_close(socket);esp_transport_destroy(socket);socket=NULL;}
    if(ssl){esp_transport_destroy(ssl);ssl=NULL;}
    joined=false;used=frame_left=control_used=0;fragmented=false;awaiting_heartbeat=false;
    retry_at=now_ms()+retry_ms;
    retry_ms=retry_ms<15000?retry_ms*2:30000;
}
void HQ_RTStop(void)
{
    disconnect();wipe(&project_url);wipe(&public_key);wipe(&household);wipe(&token);
    memset(message,0,sizeof(message));retry_ms=1000;retry_at=0;
}
void HQ_RTConfigure(const char *url,const char *key,const char *home,const char *jwt)
{
    if(!url||!key||!*key||!home||!*home||!jwt||!*jwt||
       strlen(url)>264||strlen(key)>2048||strlen(home)>96||strlen(jwt)>8192){HQ_RTStop();return;}
    if(project_url && !strcmp(project_url,url) && !strcmp(public_key,key) && !strcmp(household,home) && !strcmp(token,jwt))return;
    /* A rotated token gets a new authenticated private join. An old account's
     * subscription never carries over to a newly selected household. */
    HQ_RTStop();project_url=strdup(url);public_key=strdup(key);household=strdup(home);token=strdup(jwt);
    if(!project_url||!public_key||!household||!token)HQ_RTStop();
}
bool HQ_RTJoined(void){return joined;}
static bool send_event(const char *topic,const char *event,cJSON *payload,unsigned ref)
{
    if(!payload)payload=cJSON_CreateObject();
    cJSON *o=cJSON_CreateObject();if(!o||!payload){cJSON_Delete(o);cJSON_Delete(payload);return false;}
    char ref_text[24];snprintf(ref_text,sizeof(ref_text),"%u",ref);
    /* Allocation failure must not turn an authenticated private join into a
     * partial message. Phoenix heartbeats have no channel join reference. */
    if(!cJSON_AddStringToObject(o,"topic",topic)||!cJSON_AddStringToObject(o,"event",event)||
       !cJSON_AddStringToObject(o,"ref",ref_text)||
       !(strcmp(topic,"phoenix")?cJSON_AddStringToObject(o,"join_ref","1"):cJSON_AddNullToObject(o,"join_ref"))||
       !cJSON_AddItemToObject(o,"payload",payload)){cJSON_Delete(payload);cJSON_Delete(o);return false;}
    char *s=cJSON_PrintUnformatted(o);
    cJSON *secret=cJSON_GetObjectItemCaseSensitive(payload,"access_token");
    if(cJSON_IsString(secret))memset(secret->valuestring,0,strlen(secret->valuestring));
    cJSON_Delete(o);
    if(!s)return false;
    size_t n=strlen(s);
    bool ok=esp_transport_ws_send_raw(socket,WS_TRANSPORT_OPCODES_TEXT|WS_TRANSPORT_OPCODES_FIN,s,n,1000)==(int)n;
    memset(s,0,n);free(s);return ok;
}
static bool connect_home(void)
{
    if(strncmp(project_url,"https://",8))return false;
    char host[256];const char *end=strchr(project_url+8,'/');
    size_t n=end?(size_t)(end-(project_url+8)):strlen(project_url+8);
    if(!n||n>=sizeof(host))return false;
    memcpy(host,project_url+8,n);host[n]=0;
    int port=443;char *colon=strchr(host,':');
    if(colon){
        char *port_end;long value=strtol(colon+1,&port_end,10);
        if(!colon[1]||*port_end||value<1||value>65535)return false;
        port=(int)value;*colon=0;
    }
    if(!host[0]||(end&&strcmp(end,"/")))return false;
    for(const char *p=host;*p;p++)if(!isalnum((unsigned char)*p)&&*p!='.'&&*p!='-')return false;
    size_t key_length=strlen(public_key);
    if(!key_length||key_length>2048||strlen(household)>96)return false;
    for(const char *p=household;*p;p++)if(!isalnum((unsigned char)*p)&&*p!='-'&&*p!='_')return false;
    char *path=malloc(key_length*3+80);
    if(!path)return false;
    /* A publishable key is a query value, so reserved bytes must not become
     * another URL parameter or a line in the WebSocket upgrade request. */
    static const char prefix[]="/realtime/v1/websocket?apikey=";
    static const char hex[]="0123456789ABCDEF";
    memcpy(path,prefix,sizeof(prefix));char *out=path+sizeof(prefix)-1;
    for(const unsigned char *p=(const unsigned char *)public_key;*p;p++) {
        if(isalnum(*p)||*p=='-'||*p=='_'||*p=='.'||*p=='~')*out++=*p;
        else {*out++='%';*out++=hex[*p>>4];*out++=hex[*p&15];}
    }
    strcpy(out,"&vsn=1.0.0");
    ssl=esp_transport_ssl_init();socket=ssl?esp_transport_ws_init(ssl):NULL;
    if(!socket){free(path);return false;}
    esp_transport_ssl_crt_bundle_attach(ssl,esp_crt_bundle_attach);
    /* IDF 5.3's automatic CLOSE handler returns zero, indistinguishable from a
     * timeout. Propagating controls lets us leave Joined immediately and answer
     * PING even between a text frame and its continuation. */
    esp_transport_ws_config_t config={.ws_path=path,.propagate_control_frames=true};
    bool ok=esp_transport_ws_set_config(socket,&config)==ESP_OK && esp_transport_connect(socket,host,port,8000)==0;
    free(path);if(!ok)return false;
    char topic[128];snprintf(topic,sizeof(topic),"realtime:homehq:%s",household);
    cJSON *payload=cJSON_Parse("{\"config\":{\"broadcast\":{\"self\":false,\"ack\":false},\"presence\":{\"enabled\":false},\"private\":true,\"postgres_changes\":[]}}");
    if(!payload||!cJSON_AddStringToObject(payload,"access_token",token)){cJSON_Delete(payload);return false;}
    reference=1;ok=send_event(topic,"phx_join",payload,reference);
    join_until=now_ms()+10000;heartbeat_at=now_ms()+25000;
    return ok;
}
static void received(void)
{
    message[used]=0;
    if(memchr(message,0,used)){disconnect();return;}
    cJSON *o=cJSON_ParseWithLengthOpts(message,used+1,NULL,true);
    if(!cJSON_IsObject(o)){cJSON_Delete(o);disconnect();return;}
    const char *event=str(o,"event"),*ref=str(o,"ref");
    const cJSON *payload=cJSON_GetObjectItemCaseSensitive(o,"payload");
    char topic[128];snprintf(topic,sizeof(topic),"realtime:homehq:%s",household);
    if(!strcmp(event,"phx_reply")) {
        if(!joined && !strcmp(ref,"1") && !strcmp(str(o,"topic"),topic)) {
            if(!strcmp(str(payload,"status"),"ok")){joined=true;retry_ms=1000;HQ_ServiceRefresh();}
            else disconnect();
        } else if(awaiting_heartbeat && !strcmp(str(o,"topic"),"phoenix")) {
            char expected[24];snprintf(expected,sizeof(expected),"%u",heartbeat_ref);
            if(!strcmp(ref,expected)) {
                if(!strcmp(str(payload,"status"),"ok"))awaiting_heartbeat=false;
                else disconnect();
            }
        }
    } else if(!strcmp(str(o,"topic"),topic)) {
        if(joined && !strcmp(event,"broadcast") && !strcmp(str(payload,"event"),"changed"))HQ_ServiceRefresh();
        else if(!strcmp(event,"phx_error")||!strcmp(event,"phx_close"))disconnect();
    }
    cJSON_Delete(o);
}
void HQ_RTPoll(void)
{
    if(!project_url)return;
    int64_t now=now_ms();
    if(!socket){if(now>=retry_at && !connect_home())disconnect();return;}
    if((!joined && now>=join_until)||(awaiting_heartbeat && now>=acknowledgement_until)){disconnect();return;}
    if(now>=heartbeat_at) {
        heartbeat_ref=++reference;awaiting_heartbeat=true;acknowledgement_until=now+10000;heartbeat_at=now+25000;
        if(!send_event("phoenix","heartbeat",cJSON_CreateObject(),heartbeat_ref)){disconnect();return;}
    }
    /* Read at most four small pieces per worker turn. Invalidation messages
     * coalesce; they cannot monopolize the command queue or display task. */
    char input[1024];
    for(unsigned turn=0;turn<4;turn++){
        int n=esp_transport_read(socket,input,sizeof(input),5);
        if(n<0){disconnect();return;}
        int opcode=esp_transport_ws_get_read_opcode(socket);
        if(opcode==WS_TRANSPORT_OPCODES_NONE){if(frame_left)disconnect();break;}
        bool is_control=opcode==WS_TRANSPORT_OPCODES_CLOSE||opcode==WS_TRANSPORT_OPCODES_PING||opcode==WS_TRANSPORT_OPCODES_PONG;
        if(!frame_left){
            int payload=esp_transport_ws_get_read_payload_len(socket);
            frame_fin=esp_transport_ws_get_fin_flag(socket);frame_opcode=(unsigned)opcode;
            if(payload<0){disconnect();return;}
            if(is_control){
                if(!frame_fin||payload>125||(opcode==WS_TRANSPORT_OPCODES_CLOSE&&payload==1)){disconnect();return;}
                control_used=0;
            } else {
                if((unsigned)payload>MESSAGE_MAX-used||
                   (opcode==WS_TRANSPORT_OPCODES_TEXT&&fragmented)||
                   (opcode==WS_TRANSPORT_OPCODES_CONT&&!fragmented)||
                   (opcode!=WS_TRANSPORT_OPCODES_TEXT&&opcode!=WS_TRANSPORT_OPCODES_CONT)){disconnect();return;}
                if(opcode==WS_TRANSPORT_OPCODES_TEXT&&!frame_fin)fragmented=true;
            }
            frame_left=(unsigned)payload;
        } else if((unsigned)opcode!=frame_opcode||frame_fin!=esp_transport_ws_get_fin_flag(socket)){disconnect();return;}
        /* ws_read drops IDF's partial-frame state after a payload read timeout.
         * Reconnect instead of mistaking the next header for that old payload. */
        if((!n&&frame_left)||(unsigned)n>frame_left){disconnect();return;}
        frame_left-=(unsigned)n;
        if(is_control){memcpy(control+control_used,input,n);control_used+=(unsigned)n;}
        else {memcpy(message+used,input,n);used+=(unsigned)n;}
        if(frame_left)continue;
        if(is_control){
            if(opcode==WS_TRANSPORT_OPCODES_PING){
                if(esp_transport_ws_send_raw(socket,WS_TRANSPORT_OPCODES_PONG|WS_TRANSPORT_OPCODES_FIN,control,control_used,1000)!=(int)control_used){disconnect();return;}
            } else if(opcode==WS_TRANSPORT_OPCODES_CLOSE){
                esp_transport_ws_send_raw(socket,WS_TRANSPORT_OPCODES_CLOSE|WS_TRANSPORT_OPCODES_FIN,control,control_used,1000);
                disconnect();return;
            }
        } else if(frame_fin){received();used=0;fragmented=false;if(!socket)return;}
    }
}
