#include <assert.h>
#include <stdio.h>
#define HQ_SERVICE_HOST_TEST 1
#include "../src/homehq_service.c"
const char homehq_demo_json[] = "{\"schema_version\":1,\"revision\":1,\"home\":{\"id\":\"house\",\"demo\":true},\"viewer\":{\"user_id\":\"u1\"},\"people\":[],\"events\":[],\"photos\":[],\"shopping\":[{\"id\":\"g1\",\"done\":false,\"version\":1}],\"chores\":[{\"id\":\"c1\",\"done\":false,\"version\":7}],\"devices\":[{\"id\":\"d1\",\"on\":false,\"version\":1}]}";
void HQ_RTStop(void) {}
void HQ_RTPoll(void) {}
bool HQ_RTJoined(void) { return false; }
void HQ_RTConfigure(const char *url,const char *key,const char *home,const char *jwt) { (void)url;(void)key;(void)home;(void)jwt; }
static unsigned photo_resets;
void HQ_PhotoReset(void) { ++photo_resets; }
bool HQ_PhotoDownload(const char *url,const char *jwt,const char *key) { (void)url;(void)jwt;(void)key;return true; }
static cJSON *json(const char *text) { cJSON *v=cJSON_Parse(text);assert(v);return v; }
static cJSON *chore(bool done,int version) { char text[150];snprintf(text,sizeof text,"{\"kind\":\"chore\",\"id\":\"c1\",\"done\":%s,\"version\":%d}",done?"true":"false",version);return json(text); }
int main(void)
{
    HQ_ServiceInit();
    cJSON *first=HQ_ServicePoll();assert(first);cJSON_Delete(first);
    cJSON *provision=json("{\"wifi_ssid\":\"test-network\",\"wifi_password\":\"\",\"url\":\"https://test.supabase.co\",\"key\":\"sb_publishable_test\",\"email\":\"test@example.com\",\"password\":\"temporary\"}");
    assert(HQ_ServiceConfigure(provision));cJSON_Delete(provision);
    cJSON *session=json("{\"access_token\":\"test.jwt.signature\",\"refresh_token\":\"rotated\",\"expires_in\":3600,\"user\":{\"id\":\"u1\"}}");
    fake_nvs_failure=1;
    assert(!auth_install(session,generation,true));assert(!session_durable);
    cJSON *snapshot=demo();cJSON_Delete(base);base=snapshot;
    cJSON *command=chore(true,7);
    assert(!HQ_ServiceCommand(command));assert(cJSON_GetArraySize(outbox)==0);
    fake_nvs_failure=0;assert(save_session_locked());
    scrub_login(configuration_intent);configuration_intent=NULL;
    assert(HQ_ServiceCommand(command));assert(cJSON_GetArraySize(outbox)==1);
    cJSON *sent=cJSON_Duplicate(cJSON_GetArrayItem(outbox,0),true);
    cJSON *undo=chore(false,999);
    assert(HQ_ServiceCommand(undo));
    assert(cJSON_GetArraySize(outbox)==1);
    assert(field(cJSON_GetArrayItem(outbox,0),"version")->valueint==7);
    cJSON *reply=json("{\"status\":\"saved\",\"item\":{\"id\":\"c1\",\"done\":true,\"version\":8},\"revision\":2}");
    acknowledge_locked(sent,reply);assert(cJSON_GetArraySize(outbox)==1);
    assert(field(cJSON_GetArrayItem(outbox,0),"version")->valueint==8);
    assert(cJSON_IsFalse(field(find_row(delivery,command),"done")));
    assert(!HQ_ServiceLogout());
    assert(HQ_ServiceSignIn("test@example.com","temporary"));
    cJSON *other=json("{\"access_token\":\"other.jwt.signature\",\"refresh_token\":\"other\",\"expires_in\":3600,\"user\":{\"id\":\"u2\"}}");
    assert(!auth_install(other,generation,true));assert(!strcmp(user_id,"u1"));
    scrub_login(configuration_intent);configuration_intent=NULL;
    fake_nvs_failure=1;
    assert(!HQ_ServiceCommand(command));assert(cJSON_IsFalse(field(cJSON_GetArrayItem(outbox,0),"done")));
    fake_nvs_failure=0;
    cJSON *conflict=json("{\"status\":\"conflict\",\"item\":{\"id\":\"c1\",\"done\":true,\"version\":9},\"revision\":3}");
    acknowledge_locked(cJSON_GetArrayItem(outbox,0),conflict);
    assert(cJSON_GetArraySize(outbox)==0);assert(cJSON_IsTrue(field(find_row(delivery,command),"done")));
    assert(save_cache_worker());
    cJSON *cached=load_cache_locked();assert(cached);cJSON_Delete(cached);
    replace_string(&user_id,"u2");assert(!load_cache_locked());replace_string(&user_id,"u1");
    /* The 33rd distinct offline mutation is rejected without changing the 32
     * durable desired values already accepted by the application. */
    cJSON *shopping=cJSON_GetObjectItemCaseSensitive(base,"shopping");
    for(unsigned i=0;i<33;i++) {
        char text[180];snprintf(text,sizeof text,"{\"id\":\"bounded%u\",\"done\":false,\"version\":1}",i);
        cJSON_AddItemToArray(shopping,json(text));
        snprintf(text,sizeof text,"{\"kind\":\"shopping\",\"id\":\"bounded%u\",\"done\":true,\"version\":1}",i);
        cJSON *change=json(text);assert(HQ_ServiceCommand(change)==(i<32));cJSON_Delete(change);
    }
    assert(cJSON_GetArraySize(outbox)==32);assert(!HQ_ServiceLogout());
    while(cJSON_GetArraySize(outbox)) {
        cJSON *head=cJSON_GetArrayItem(outbox,0);char text[220];
        snprintf(text,sizeof text,"{\"status\":\"saved\",\"item\":{\"id\":\"%s\",\"done\":true,\"version\":2},\"revision\":4}",string_field(head,"id"));
        cJSON *saved=json(text);assert(acknowledge_locked(head,saved));cJSON_Delete(saved);
    }
    unsigned old_generation=generation;
    assert(HQ_ServiceLogout());assert(photo_resets);assert(!access_token && !refresh_token && !user_id);
    cJSON *stale=demo();assert(!install_snapshot(stale,old_generation));cJSON_Delete(stale);
    cJSON *session_disk=read_json("session",2048);assert(!session_disk);
    cJSON *cfg_disk=read_json("config",4096);assert(cfg_disk);assert(!field(cfg_disk,"password"));assert(!field(cfg_disk,"email"));cJSON_Delete(cfg_disk);
    assert(!HQ_ServicePhotoRequest("other/not-our-home.png"));
    fake_busy=1;assert(!HQ_ServicePoll());fake_busy=0;
    response_t body={0};unsigned char *oversize=calloc(1,RESPONSE_MAX+1);esp_http_client_event_t event={.event_id=HTTP_EVENT_ON_DATA,.data_len=RESPONSE_MAX+1,.data=oversize,.user_data=&body};
    assert(http_event(&event)==ESP_FAIL && body.overflow);free(oversize);free(body.data);
    assert(!safe_url("http://test.supabase.co"));assert(!safe_url("https://test.supabase.co/path"));assert(!ordinary_key("sb_secret_forbidden"));
    cJSON_Delete(command);cJSON_Delete(undo);cJSON_Delete(sent);cJSON_Delete(reply);cJSON_Delete(conflict);cJSON_Delete(session);cJSON_Delete(other);
    cJSON_Delete(config);cJSON_Delete(base);cJSON_Delete(outbox);cJSON_Delete(delivery);scrub_login(configuration_intent);cJSON_Delete(logout_credentials);
    wipe_free(access_token);wipe_free(refresh_token);wipe_free(user_id);
    for(unsigned i=0;i<16;i++)free(fake_nvs[i].data);
    puts("PASS service: durable rotation, coalescing, in-flight presses, conflicts, account guards, logout, cache, bounded HTTP");
    return 0;
}
