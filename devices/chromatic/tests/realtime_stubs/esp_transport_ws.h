#pragma once
#include "esp_transport.h"
typedef int ws_transport_opcodes_t;
enum {WS_TRANSPORT_OPCODES_CONT=0,WS_TRANSPORT_OPCODES_TEXT=1,WS_TRANSPORT_OPCODES_BINARY=2,
      WS_TRANSPORT_OPCODES_CLOSE=8,WS_TRANSPORT_OPCODES_PING=9,WS_TRANSPORT_OPCODES_PONG=10,
      WS_TRANSPORT_OPCODES_FIN=128,WS_TRANSPORT_OPCODES_NONE=256};
typedef struct {const char *ws_path;bool propagate_control_frames;} esp_transport_ws_config_t;
void *esp_transport_ws_init(void *);
int esp_transport_ws_set_config(void *,const esp_transport_ws_config_t *);
int esp_transport_ws_send_raw(void *,int,const char *,int,int);
int esp_transport_ws_get_read_opcode(void *);
int esp_transport_ws_get_read_payload_len(void *);
bool esp_transport_ws_get_fin_flag(void *);
