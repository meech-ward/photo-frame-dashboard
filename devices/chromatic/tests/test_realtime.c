#include "homehq.h"
#include "homehq_realtime.h"
#include "esp_transport_ws.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int64_t clock_ms;
static unsigned refreshes, verified, connects, closes, ssl_destroyed, ws_destroyed, sends;
static char *sent;
static char *path_seen;
static unsigned sent_opcode, sent_length;
static bool fail_send, fail_connect, fail_ws, read_timeout, active_connection;
typedef struct {const char *bytes;unsigned length;int opcode;bool fin;} Frame;
static const Frame *frames;
static unsigned frame_count, frame_index, position, chunk=17;
static int read_opcode=WS_TRANSPORT_OPCODES_NONE;
static unsigned read_length;
static bool read_fin;

int64_t esp_timer_get_time(void){return clock_ms*1000;}
int esp_crt_bundle_attach(void *x){(void)x;return 0;}
void HQ_ServiceRefresh(void){refreshes++;}
void *esp_transport_ssl_init(void){return (void*)1;}
void *esp_transport_ws_init(void *x){assert(x==(void*)1);return fail_ws?NULL:(void*)2;}
void esp_transport_ssl_crt_bundle_attach(void *x,int (*f)(void*)){assert(x==(void*)1 && f==esp_crt_bundle_attach);verified++;}
int esp_transport_ws_set_config(void *x,const esp_transport_ws_config_t *config)
{
    assert(x && strstr(config->ws_path,"apikey=sb_publishable_test") && config->propagate_control_frames);
    assert(!strchr(config->ws_path,'\r')&&!strchr(config->ws_path,'\n'));
    free(path_seen);path_seen=strdup(config->ws_path);assert(path_seen);
    return 0;
}
int esp_transport_close(void *x){assert(x==(void*)2);closes++;active_connection=false;return 0;}
int esp_transport_destroy(void *x){assert(x);if(x==(void*)1)ssl_destroyed++;else {assert(x==(void*)2);ws_destroyed++;}return 0;}
int esp_transport_connect(void *x,const char *host,int port,int timeout)
{assert(x && !strcmp(host,"project.supabase.co") && port==443 && timeout==8000);connects++;active_connection=!fail_connect;return fail_connect?-1:0;}
int esp_transport_ws_send_raw(void *x,int opcode,const char *data,int n,int timeout)
{
    assert(x && timeout==1000 && n>=0);sends++;sent_opcode=opcode;sent_length=n;
    free(sent);sent=malloc(n+1);memcpy(sent,data,n);sent[n]=0;
    return fail_send?-1:n;
}
int esp_transport_read(void *x,char *out,int n,int timeout)
{
    assert(x && timeout==5);
    while(frame_index<frame_count && position==frames[frame_index].length && position) {frame_index++;position=0;}
    if(frame_index>=frame_count){read_opcode=WS_TRANSPORT_OPCODES_NONE;return 0;}
    const Frame *frame=&frames[frame_index];read_opcode=frame->opcode;read_length=frame->length;read_fin=frame->fin;
    if(read_timeout){read_timeout=false;return 0;}
    if(!frame->length){frame_index++;position=0;return 0;}
    unsigned length=frame->length-position;if(length>chunk)length=chunk;if(length>(unsigned)n)length=n;
    memcpy(out,frame->bytes+position,length);position+=length;return length;
}
int esp_transport_ws_get_read_opcode(void *x){assert(x);return read_opcode;}
int esp_transport_ws_get_read_payload_len(void *x){assert(x);return read_length;}
bool esp_transport_ws_get_fin_flag(void *x){assert(x);return read_fin;}

static const char *join_reply="{\"topic\":\"realtime:homehq:household\",\"event\":\"phx_reply\",\"ref\":\"1\",\"payload\":{\"status\":\"ok\"}}";
static const char *hint="{\"topic\":\"realtime:homehq:household\",\"event\":\"broadcast\",\"payload\":{\"event\":\"changed\",\"payload\":{\"revision\":2}}}";
static void receive_frames(const Frame *wire,unsigned count)
{
    frames=wire;frame_count=count;frame_index=position=0;
    for(unsigned attempts=0;frame_index<count && attempts<1000;attempts++) {
        HQ_RTPoll();
        if(!active_connection)break;
        if(frame_index<count && frames[frame_index].length && position==frames[frame_index].length && frame_index==count-1)break;
    }
    frames=NULL;frame_count=frame_index=position=0;read_opcode=WS_TRANSPORT_OPCODES_NONE;
}
static void receive(const char *wire)
{Frame frame={wire,(unsigned)strlen(wire),WS_TRANSPORT_OPCODES_TEXT,true};receive_frames(&frame,1);}
static void configure(void)
{
    HQ_RTStop();frames=NULL;frame_count=frame_index=position=0;
    HQ_RTConfigure("https://project.supabase.co","sb_publishable_test","household","test_access");HQ_RTPoll();
    assert(!HQ_RTJoined() && sent_opcode==129);
}
static void join(void){configure();receive(join_reply);assert(HQ_RTJoined());}
static void check_join(void)
{
    cJSON *wire=cJSON_Parse(sent);assert(wire);
    const cJSON *payload=cJSON_GetObjectItemCaseSensitive(wire,"payload");
    const cJSON *config=cJSON_GetObjectItemCaseSensitive(payload,"config");
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(config,"private")));
    assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(config,"presence"),"enabled")));
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(payload,"access_token")->valuestring,"test_access"));
    cJSON_Delete(wire);
}
static void test_private_join_and_hints(void)
{
    configure();check_join();assert(verified==1 && connects==1);
    receive(hint);assert(!refreshes);
    receive(join_reply);assert(HQ_RTJoined() && refreshes==1);
    receive("{\"topic\":\"realtime:homehq:other\",\"event\":\"broadcast\",\"payload\":{\"event\":\"changed\"}}");assert(refreshes==1);
    receive(hint);assert(refreshes==2);
    size_t split=41;
    Frame fragmented[]={{hint,split,WS_TRANSPORT_OPCODES_TEXT,false},
                        {"ping",4,WS_TRANSPORT_OPCODES_PING,true},
                        {hint+split,(unsigned)(strlen(hint)-split),WS_TRANSPORT_OPCODES_CONT,true}};
    receive_frames(fragmented,3);assert(HQ_RTJoined() && refreshes==3);
    assert(sent_opcode==(WS_TRANSPORT_OPCODES_PONG|WS_TRANSPORT_OPCODES_FIN) && !strcmp(sent,"ping"));
    Frame ping={"",0,WS_TRANSPORT_OPCODES_PING,true};receive_frames(&ping,1);
    assert(HQ_RTJoined() && sent_opcode==138 && sent_length==0);
    char maximum_ping[125];memset(maximum_ping,'p',sizeof(maximum_ping));
    Frame full_ping={maximum_ping,sizeof(maximum_ping),WS_TRANSPORT_OPCODES_PING,true};receive_frames(&full_ping,1);
    assert(HQ_RTJoined() && sent_opcode==138 && sent_length==125 && !memcmp(sent,maximum_ping,125));
}
static void test_heartbeat_and_rotation(void)
{
    join();clock_ms+=25001;HQ_RTPoll();assert(strstr(sent,"heartbeat"));
    cJSON *wire=cJSON_Parse(sent);assert(cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(wire,"join_ref")));cJSON_Delete(wire);
    receive("{\"topic\":\"phoenix\",\"event\":\"phx_reply\",\"ref\":\"2junk\",\"payload\":{\"status\":\"ok\"}}");
    clock_ms+=10001;HQ_RTPoll();assert(!HQ_RTJoined());
    join();clock_ms+=25001;HQ_RTPoll();
    receive("{\"topic\":\"phoenix\",\"event\":\"phx_reply\",\"ref\":\"2\",\"payload\":{\"status\":\"ok\"}}");
    clock_ms+=10001;HQ_RTPoll();assert(HQ_RTJoined());
    HQ_RTConfigure("https://project.supabase.co","sb_publishable_test","household","rotated_access");
    assert(!HQ_RTJoined());HQ_RTPoll();assert(strstr(sent,"rotated_access"));
    receive("{\"topic\":\"realtime:homehq:household\",\"event\":\"phx_reply\",\"ref\":\"1\",\"payload\":{\"status\":\"error\"}}");assert(!HQ_RTJoined());
    join();clock_ms+=25001;HQ_RTPoll();
    receive("{\"topic\":\"phoenix\",\"event\":\"phx_reply\",\"ref\":\"2\",\"payload\":{\"status\":\"error\"}}");assert(!HQ_RTJoined());
}
static void test_close_fragment_and_retry(void)
{
    join();unsigned before=connects;
    Frame close={"",0,WS_TRANSPORT_OPCODES_CLOSE,true};receive_frames(&close,1);
    assert(!HQ_RTJoined() && sent_opcode==136 && sent_length==0);
    HQ_RTPoll();assert(connects==before);clock_ms+=1000;HQ_RTPoll();assert(connects==before+1);
    receive(join_reply);assert(HQ_RTJoined());
    Frame unexpected={hint,(unsigned)strlen(hint),WS_TRANSPORT_OPCODES_CONT,true};
    receive_frames(&unexpected,1);assert(!HQ_RTJoined());
    join();
    Frame second_text[]={{hint,17,WS_TRANSPORT_OPCODES_TEXT,false},
                         {hint,(unsigned)strlen(hint),WS_TRANSPORT_OPCODES_TEXT,true}};
    receive_frames(second_text,2);assert(!HQ_RTJoined());
    join();Frame bad_ping={"x",1,WS_TRANSPORT_OPCODES_PING,false};receive_frames(&bad_ping,1);assert(!HQ_RTJoined());
    join();Frame long_ping={hint,126,WS_TRANSPORT_OPCODES_PING,true};receive_frames(&long_ping,1);assert(!HQ_RTJoined());
    join();Frame short_close={"x",1,WS_TRANSPORT_OPCODES_CLOSE,true};receive_frames(&short_close,1);assert(!HQ_RTJoined());
    join();Frame status_close={"\x03\xE8",2,WS_TRANSPORT_OPCODES_CLOSE,true};receive_frames(&status_close,1);
    assert(!HQ_RTJoined() && sent_length==2 && !memcmp(sent,"\x03\xE8",2));
    join();char huge[8193];memset(huge,' ',sizeof(huge));
    Frame too_large={huge,sizeof(huge),WS_TRANSPORT_OPCODES_TEXT,true};receive_frames(&too_large,1);assert(!HQ_RTJoined());
    join();receive("{}junk");assert(!HQ_RTJoined());
    join();read_timeout=true;receive(hint);assert(!HQ_RTJoined());
    join();fail_send=true;clock_ms+=25001;HQ_RTPoll();fail_send=false;assert(!HQ_RTJoined());
    unsigned destroyed=ssl_destroyed;HQ_RTStop();fail_ws=true;
    HQ_RTConfigure("https://project.supabase.co","sb_publishable_test","household","test_access");HQ_RTPoll();
    fail_ws=false;assert(ssl_destroyed==destroyed+1);
    HQ_RTStop();fail_connect=true;
    HQ_RTConfigure("https://project.supabase.co","sb_publishable_test","household","test_access");HQ_RTPoll();
    fail_connect=false;HQ_RTStop();assert(closes==ws_destroyed && ssl_destroyed==ws_destroyed+1);
}
static void test_url_and_query_values(void)
{
    const char *invalid[]={"https://project.supabase.co:443oops", "https://project.supabase.co:0",
                          "https://project.supabase.co@other.invalid", "https://project.supabase.co/realtime",
                          "https://project.supabase.co?extra=value"};
    for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        HQ_RTStop();unsigned before=connects;
        HQ_RTConfigure(invalid[i],"sb_publishable_test","household","test_access");HQ_RTPoll();
        assert(connects==before && !HQ_RTJoined());
    }
    HQ_RTStop();
    HQ_RTConfigure("https://project.supabase.co","sb_publishable_test&vsn=2.0.0\r\nX: y","household","test_access");HQ_RTPoll();
    assert(strstr(path_seen,"test%26vsn%3D2.0.0%0D%0AX%3A%20y&vsn=1.0.0"));
    HQ_RTStop();
}
static unsigned allocation, fail_at;
static void *failing_malloc(size_t size){return allocation++==fail_at?NULL:malloc(size);}
static void test_allocation_failures_never_send_partial_private_join(void)
{
    cJSON_Hooks hooks={failing_malloc,free};
    for(fail_at=0;fail_at<90;fail_at++) {
        HQ_RTStop();allocation=0;unsigned before=sends;
        HQ_RTConfigure("https://project.supabase.co","sb_publishable_test","household","test_access");
        cJSON_InitHooks(&hooks);HQ_RTPoll();cJSON_InitHooks(NULL);
        if(sends!=before)check_join();
    }
    HQ_RTStop();assert(closes==ws_destroyed && ssl_destroyed==ws_destroyed+1);
}
int main(void)
{
    test_private_join_and_hints();test_heartbeat_and_rotation();test_close_fragment_and_retry();
    test_url_and_query_values();
    test_allocation_failures_never_send_partial_private_join();
    free(sent);free(path_seen);puts("Private join, frame/control ordering, closure, heartbeat, retry, URL encoding, token rotation and allocation failures PASS");return 0;
}
