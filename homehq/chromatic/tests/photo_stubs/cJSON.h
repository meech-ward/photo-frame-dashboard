#pragma once
#include <stdbool.h>
typedef struct cJSON {
    const char *string;
    char *valuestring;
    struct cJSON *child, *next;
} cJSON;
const cJSON *cJSON_GetObjectItemCaseSensitive(const cJSON *object, const char *key);
bool cJSON_IsString(const cJSON *value);
