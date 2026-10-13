#include <assert.h>
#include <stdio.h>
#define HQ_SERVICE_HOST_TEST 1
#include "../src/homehq_service.c"
const char homehq_demo_json[] = "{\"schema_version\":1,\"revision\":1,\"home\":{\"id\":\"house\",\"demo\":true},\"viewer\":{\"user_id\":\"u1\"},\"people\":[],\"events\":[],\"photos\":[],\"shopping\":[{\"id\":\"g1\",\"done\":false,\"version\":1}],\"chores\":[{\"id\":\"c1\",\"done\":false,\"version\":7}],\"devices\":[{\"id\":\"d1\",\"on\":false,\"version\":1}]}";
void HQ_RTStop(void) {}
void HQ_RTPoll(void) {}
bool HQ_RTJoined(void) { return false; }
void HQ_RTConfigure(const char *url,const char *key,const char *home,const char *jwt) { (void)url;(void)key;(void)home;(void)jwt; }
static unsigned photo_resets, photo_restore_calls, photo_clear_calls;
static bool photo_restore_hit, photo_clear_failure, photo_invalidate_during_restore;
void HQ_PhotoReset(void) { ++photo_resets; }
bool HQ_PhotoClearCache(void) { ++photo_clear_calls;return !photo_clear_failure; }
bool HQ_PhotoRestore(const char *user,const char *path,HQ_PhotoGuard check,void *context) {
    assert(user&&*user&&path&&*path);++photo_restore_calls;
    assert(check(context));
    if(photo_invalidate_during_restore) ++generation;
    return photo_restore_hit&&check(context);
}
bool HQ_PhotoDownload(const char *url,const char *jwt,const char *key,const char *user,HQ_PhotoGuard check,void *context,uint8_t *dictionary,size_t capacity) {
    (void)url;(void)jwt;(void)key;assert(user&&*user);
    assert(dictionary==(uint8_t *)http_scratch&&dictionary!=(uint8_t *)base_wire&&capacity==RESPONSE_MAX+1);
    memset(dictionary,0xd7,RESPONSE_MAX);return check(context);
}
static cJSON *json(const char *text) { cJSON *v=cJSON_Parse(text);assert(v);return v; }
static cJSON *chore(bool done,int version) { char text[150];snprintf(text,sizeof text,"{\"kind\":\"chore\",\"id\":\"c1\",\"done\":%s,\"version\":%d}",done?"true":"false",version);return json(text); }
static bool receive_snapshot(const char *wire,unsigned request_generation)
{
    assert(reserve_wire_buffers_locked());assert(strlen(wire)<=RESPONSE_MAX);
    memmove(http_scratch,wire,strlen(wire)+1);
    return install_snapshot_wire(http_scratch,request_generation);
}
static bool save_current_cache(void)
{
    memcpy(http_scratch,base_wire,strlen(base_wire)+1);
    return save_cache_candidate(http_scratch,generation);
}
static void check_photo_worker(void)
{
    uint64_t intent=0;
    assert(nvs_get_u64(store,"photo_clear",&intent)==ESP_OK&&intent==1);
    photo_clear_failure=true;clear_photo_cache_worker();assert(photo_cache_clear_pending);
    /* A same-account new durable session cannot forget an earlier failed
     * clear when boot reconstructs RAM from NVS. */
    assert(save_session_locked());photo_cache_clear_pending=false;restore_photo_clear_locked();assert(photo_cache_clear_pending);
    photo_clear_failure=false;fake_time_ms+=5001;clear_photo_cache_worker();assert(!photo_cache_clear_pending);
    assert(nvs_get_u64(store,"photo_clear",&intent)==ESP_OK&&!intent);
    char *token=access_token;access_token=NULL;time_t utc=fake_clock_epoch;fake_clock_epoch=0;
    char *canonical=base_wire,*inactive=http_scratch;
    assert(!xEventGroupGetBits(wifi_events));assert(HQ_ServicePhotoRequest("house/cache.png"));
    photo_restore_hit=true;unsigned before=photo_restore_calls;
    fake_calloc_failures=2;
    assert(restore_photo_worker(generation)&&photo_restore_calls==before+1&&!photo_request[0]&&http_scratch);
    assert(fake_calloc_failures==2&&base_wire==canonical&&http_scratch==inactive);fake_calloc_failures=0;
    assert(HQ_ServicePhotoRequest("house/missing.png"));photo_restore_hit=false;before=photo_restore_calls;
    assert(!restore_photo_worker(generation)&&photo_restore_calls==before+1&&photo_request[0]&&http_scratch);
    assert(!restore_photo_worker(generation)&&photo_restore_calls==before+1);
    photo_restore_retry_at=0;photo_restore_hit=true;photo_invalidate_during_restore=true;unsigned resets=photo_resets;
    assert(!restore_photo_worker(generation)&&photo_resets==resets+1&&http_scratch);
    photo_invalidate_during_restore=false;photo_restore_hit=false;photo_request[0]=photo_restore_path[0]=0;
    assert(base_wire==canonical&&http_scratch==inactive);
    PhotoContext context={.generation=generation};snprintf(context.user,sizeof context.user,"%s",user_id);snprintf(context.home,sizeof context.home,"%s",base_info.home);
    assert(HQ_PhotoDownload("https://test.supabase.co/photo","ordinary-token","public-key",user_id,photo_current,&context,
                            (uint8_t *)http_scratch,RESPONSE_MAX+1));
    HQ_WireInfo metadata;assert(HQ_WireValidate(base_wire,strlen(base_wire),&metadata));
    assert(base_wire==canonical&&http_scratch==inactive&&(unsigned char)http_scratch[0]==0xd7);
    access_token=token;fake_clock_epoch=utc;
}
static void check_reserved_http(void)
{
    size_t length=25482;
    char *wire=malloc(RESPONSE_MAX+2);assert(wire);
    const char *fixture=getenv("HOMEHQ_HOSTED_SNAPSHOT");
    if(fixture) {
        FILE *f=fopen(fixture,"rb");assert(f);length=fread(wire,1,RESPONSE_MAX+1,f);assert(!ferror(f));assert(feof(f));fclose(f);
        assert(length<=RESPONSE_MAX);wire[length]=0;
        if(length<25482) { memset(wire+length,' ',25482-length);length=25482;wire[length]=0; }
    } else {
        size_t prefix=strlen(homehq_demo_json);memcpy(wire,homehq_demo_json,prefix);
        memset(wire+prefix,' ',length-prefix);wire[length]=0;
    }
    HQ_WireInfo metadata;assert(HQ_WireValidate(wire,length,&metadata));replace_string(&user_id,metadata.viewer);
    cJSON *cfg=json("{\"url\":\"https://test.supabase.co\",\"key\":\"sb_publishable_test\"}");
    char *old=base_wire,*reserved=http_scratch;unsigned cleanups=fake_http_cleanups;int status=0;
    fake_http_response=wire;fake_http_response_length=length;
    char *response=http_body(cfg,"ordinary-token","/rest/v1/rpc/homehq_snapshot",NULL,&status);
    assert(status==200&&response==reserved&&strlen(response)==length&&base_wire==old);
    assert(fake_http_cleanups==cleanups+1);assert(install_snapshot_wire(response,generation));
    assert(base_wire==reserved&&http_scratch==old&&!memcmp(base_wire,wire,length+1));
    publish_locked();assert(delivery_dirty);
    assert(!HQ_ServicePollViewWire("invalid")&&delivery_dirty);
    char *page=HQ_ServicePollViewWire("shopping");assert(page&&!delivery_dirty&&strlen(page)<length);free(page);
    assert(save_current_cache());char *cache=load_cache_locked();assert(cache&&!memcmp(cache,wire,length+1));free(cache);
    old=base_wire;reserved=http_scratch;
    fake_http_response="{\"schema_version\":1,";fake_http_response_length=strlen(fake_http_response);
    response=http_body(cfg,"ordinary-token","/snapshot",NULL,&status);assert(response==reserved);
    assert(!install_snapshot_wire(response,generation)&&base_wire==old&&!memcmp(base_wire,wire,length+1));
    assert(!save_cache_candidate(response,generation));cache=load_cache_locked();assert(cache&&!memcmp(cache,wire,length+1));free(cache);
    fake_http_response=wire;fake_http_response_length=length;fake_http_perform_failure=1;
    assert(!http_body(cfg,"ordinary-token","/snapshot",NULL,&status)&&!status&&base_wire==old&&http_scratch==reserved);
    fake_http_perform_failure=0;fake_http_init_failure=1;
    assert(!http_body(cfg,"ordinary-token","/snapshot",NULL,&status)&&base_wire==old&&http_scratch==reserved);
    fake_http_init_failure=0;
    memset(wire,'x',RESPONSE_MAX+1);fake_http_response_length=RESPONSE_MAX+1;
    assert(!http_body(cfg,"ordinary-token","/snapshot",NULL,&status)&&!status&&base_wire==old);
    fake_http_response="{\"ok\":true}";fake_http_response_length=strlen(fake_http_response);
    cJSON *small=http_json(cfg,"ordinary-token","/auth",NULL,&status);assert(cJSON_IsTrue(field(small,"ok")));
    assert(!http_scratch[0]&&base_wire==old);cJSON_Delete(small);
    assert(!receive_snapshot(homehq_demo_json,generation+1)&&base_wire==old);
    cJSON_Delete(cfg);free(wire);fake_http_response=NULL;fake_http_response_length=0;
}
int main(void)
{
    HQ_ServiceInit();
    assert(!HQ_ServiceSetClock(CLOCK_MIN_EPOCH-1));assert(!HQ_ServiceSetClock(CLOCK_MAX_EPOCH+1));
    assert(HQ_ServiceSetClock(UINT64_C(1791850000)));assert(fake_clock_epoch==1791850000);
    uint64_t saved_clock=0;assert(nvs_get_u64(store,"clock",&saved_clock)==ESP_OK&&saved_clock==1791850000);
    fake_clock_epoch=0;restore_clock_locked();assert(fake_clock_epoch==1791850000);
    unsigned clock_writes=fake_clock_writes;assert(save_clock_locked(saved_clock+60,false));assert(fake_clock_writes==clock_writes);
    fake_time_ms+=3600001;assert(save_clock_locked(saved_clock+3600,false));assert(fake_clock_writes==clock_writes+1);
    char *first=HQ_ServicePollWire();assert(first);HQ_WireInfo info;assert(HQ_WireValidate(first,strlen(first),&info));free(first);
    cJSON *ui=json(homehq_demo_json);
    cJSON *provision=json("{\"wifi_ssid\":\"test-network\",\"wifi_password\":\"\",\"url\":\"https://test.supabase.co\",\"key\":\"sb_publishable_test\",\"email\":\"test@example.com\",\"password\":\"temporary\"}");
    assert(HQ_ServiceConfigure(provision));cJSON_Delete(provision);
    cJSON *session=json("{\"access_token\":\"test.jwt.signature\",\"refresh_token\":\"rotated\",\"expires_in\":3600,\"user\":{\"id\":\"u1\"}}");
    fake_nvs_failure=1;assert(!auth_install(session,generation,true));assert(!session_durable);
    HQ_ServiceDiagnosticsInfo diagnostic;HQ_ServiceDiagnostics(&diagnostic);assert(diagnostic.configured&&!diagnostic.authenticated&&!diagnostic.session_saved);
    wifi_event_sta_disconnected_t lost={.reason=201};wifi_event(NULL,WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,&lost);
    HQ_ServiceDiagnostics(&diagnostic);assert(!diagnostic.wifi_connected&&diagnostic.wifi_disconnect_reason==201);
    cJSON *command=chore(true,7);assert(!HQ_ServiceCommand(command));assert(cJSON_GetArraySize(outbox)==0);
    fake_nvs_failure=0;assert(save_session_locked());scrub_login(configuration_intent);configuration_intent=NULL;
    assert(receive_snapshot(homehq_demo_json,generation));
    check_photo_worker();
    char *view_wire=HQ_ServiceViewWire("shopping");assert(view_wire);
    cJSON *view=json(view_wire);assert(cJSON_GetArraySize(field(view,"shopping"))==1);assert(cJSON_GetArraySize(field(view,"chores"))==0);
    assert(strstr(base_wire,"c1"));free(view_wire);cJSON_Delete(view);
    HQ_ServiceDiagnostics(&diagnostic);assert(diagnostic.authenticated&&diagnostic.session_saved&&diagnostic.revision==1&&diagnostic.clock_ready);
    wifi_initialized=true;wifi_enabled=true;unsigned connects=fake_wifi_connections;
    assert(HQ_ServiceRadio(false));assert(radio_paused&&!wifi_enabled&&fake_wifi_disconnections==1);
    wifi_event(NULL,WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,&lost);assert(fake_wifi_connections==connects);
    HQ_ServiceDiagnostics(&diagnostic);assert(diagnostic.radio_paused&&!diagnostic.wifi_enabled);
    assert(HQ_ServiceRadio(true));assert(!radio_paused&&wifi_enabled&&fake_wifi_connections==connects+1);
    wifi_event(NULL,WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,&lost);assert(fake_wifi_connections==connects+2);
    assert(HQ_ServiceCommand(command));assert(cJSON_GetArraySize(outbox)==1);HQ_ServiceOverlay(ui);
    assert(cJSON_IsTrue(field(find_row(ui,command),"done")));
    cJSON *sent=cJSON_Duplicate(cJSON_GetArrayItem(outbox,0),true),*undo=chore(false,999);
    assert(HQ_ServiceCommand(undo));assert(cJSON_GetArraySize(outbox)==1);
    assert(field(cJSON_GetArrayItem(outbox,0),"version")->valueint==7);
    cJSON *reply=json("{\"status\":\"saved\",\"item\":{\"id\":\"c1\",\"done\":true,\"version\":8},\"revision\":2}");
    assert(acknowledge_locked(sent,reply));assert(cJSON_GetArraySize(outbox)==1);
    assert(field(cJSON_GetArrayItem(outbox,0),"version")->valueint==8);HQ_ServiceOverlay(ui);
    assert(cJSON_IsFalse(field(find_row(ui,command),"done")));assert(!HQ_ServiceLogout());
    assert(HQ_ServiceSignIn("test@example.com","temporary"));
    cJSON *other=json("{\"access_token\":\"other.jwt.signature\",\"refresh_token\":\"other\",\"expires_in\":3600,\"user\":{\"id\":\"u2\"}}");
    assert(!auth_install(other,generation,true));assert(!strcmp(user_id,"u1"));
    scrub_login(configuration_intent);configuration_intent=NULL;
    fake_nvs_failure=1;assert(!HQ_ServiceCommand(command));assert(cJSON_IsFalse(field(cJSON_GetArrayItem(outbox,0),"done")));fake_nvs_failure=0;
    cJSON *conflict=json("{\"status\":\"conflict\",\"item\":{\"id\":\"c1\",\"done\":true,\"version\":9},\"revision\":3}");
    assert(acknowledge_locked(cJSON_GetArrayItem(outbox,0),conflict));assert(cJSON_GetArraySize(outbox)==0);
    assert(save_current_cache());char *cached=load_cache_locked();assert(cached);free(cached);
    replace_string(&user_id,"u2");assert(!load_cache_locked());replace_string(&user_id,"u1");
    /* Desired values stay durable even though only the UI owns their graph. */
    for(unsigned i=0;i<33;i++) {
        char text[180];snprintf(text,sizeof text,"{\"kind\":\"shopping\",\"id\":\"bounded%u\",\"done\":true,\"version\":1}",i);
        cJSON *change=json(text);assert(HQ_ServiceCommand(change)==(i<32));cJSON_Delete(change);
    }
    assert(cJSON_GetArraySize(outbox)==32);assert(!HQ_ServiceLogout());
    /* A companion deletion is authoritative; an obsolete head cannot block
     * another queue item. The streaming scanner prunes without a second tree. */
    assert(receive_snapshot(homehq_demo_json,generation));assert(cJSON_GetArraySize(outbox)==0);
    unsigned old_generation=generation;assert(HQ_ServiceLogout());assert(photo_resets);assert(!access_token&&!refresh_token&&!user_id);
    assert(!receive_snapshot(homehq_demo_json,old_generation));
    cJSON *session_disk=read_json("session",2048);assert(!session_disk);
    assert(nvs_get_u64(store,"clock",&saved_clock)==ESP_OK&&saved_clock==1791853600);
    cJSON *cfg_disk=read_json("config",4096);assert(cfg_disk);assert(!field(cfg_disk,"password"));assert(!field(cfg_disk,"email"));cJSON_Delete(cfg_disk);
    assert(!HQ_ServicePhotoRequest("other/not-our-home.png"));
    fake_busy=1;assert(!HQ_ServicePollWire());fake_busy=0;
    response_t body={0};unsigned char *oversize=calloc(1,RESPONSE_MAX+1);esp_http_client_event_t event={.event_id=HTTP_EVENT_ON_DATA,.data_len=RESPONSE_MAX+1,.data=oversize,.user_data=&body};
    assert(http_event(&event)==ESP_FAIL&&body.overflow);free(oversize);free(body.data);
    check_reserved_http();
    assert(!safe_url("http://test.supabase.co"));assert(!safe_url("https://test.supabase.co/path"));assert(!ordinary_key("sb_secret_forbidden"));
    cJSON_Delete(command);cJSON_Delete(undo);cJSON_Delete(sent);cJSON_Delete(reply);cJSON_Delete(conflict);cJSON_Delete(session);cJSON_Delete(other);cJSON_Delete(ui);
    cJSON_Delete(config);cJSON_Delete(outbox);free(base_wire);free(http_scratch);scrub_login(configuration_intent);cJSON_Delete(logout_credentials);
    wipe_free(access_token);wipe_free(refresh_token);wipe_free(user_id);for(unsigned i=0;i<16;i++)free(fake_nvs[i].data);
    puts("PASS service: wire ownership, durable rotation, coalescing, in-flight presses, conflicts, deletion, account guards, logout, cache, bounded HTTP");return 0;
}
