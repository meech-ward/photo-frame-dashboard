#include "homehq_wire.h"
#include <string.h>
#include <stdlib.h>
#include <ctype.h>
#include <errno.h>
#define DEPTH_MAX 32
#define WIRE_MAX 32768

typedef struct {
    const char *p, *end;
    HQ_WireInfo *info;
    unsigned root_seen, home_seen, viewer_seen, row_seen;
    const char *query_section, *query_id, *row_section;
    bool found;
    char row_id[128];
} Parser;
enum { OTHER, ROOT, HOME, VIEWER, ROW };

static void space(Parser *s)
{
    while (s->p < s->end && (*s->p == ' ' || *s->p == '\t' || *s->p == '\n' || *s->p == '\r')) {
        s->p++;
    }
}
static int hex(char c)
{
    return c >= '0' && c <= '9' ? c - '0' :
           c >= 'a' && c <= 'f' ? c - 'a' + 10 :
           c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}
static bool unicode(Parser *s, unsigned *value)
{
    if (s->end - s->p < 4) {
        return false;
    }
    unsigned n = 0;
    for (unsigned i = 0; i < 4; i++) {
        int h = hex(*s->p++);
        if (h < 0) {
            return false;
        }
        n = n * 16 + (unsigned)h;
    }
    *value = n;
    return true;
}
static bool utf8(Parser *s, unsigned first)
{
    unsigned count, code, min;
    if (first >= 0xc2 && first <= 0xdf) {
        count = 1;
        code = first & 31;
        min = 0x80;
    } else if (first >= 0xe0 && first <= 0xef) {
        count = 2;
        code = first & 15;
        min = 0x800;
    } else if (first >= 0xf0 && first <= 0xf4) {
        count = 3;
        code = first & 7;
        min = 0x10000;
    } else {
        return false;
    }
    if ((size_t)(s->end - s->p) < count) {
        return false;
    }
    for (unsigned i = 0; i < count; i++) {
        unsigned c = (unsigned char)*s->p++;
        if (c < 0x80 || c > 0xbf) {
            return false;
        }
        code = (code << 6) | (c & 63);
    }
    return code >= min && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff);
}
static bool string(Parser *s, char *out, size_t cap)
{
    if (s->p == s->end || *s->p++ != '"') {
        return false;
    }
    size_t n = 0;
    while (s->p < s->end) {
        unsigned c = (unsigned char)*s->p++;
        bool escaped = false;
        if (c == '"') {
            if (out && cap) {
                out[n] = 0;
            }
            return true;
        }
        if (c < 32) {
            return false;
        }
        if (c == '\\') {
            escaped = true;
            if (s->p == s->end) {
                return false;
            }
            c = (unsigned char)*s->p++;
            if (c == 'u') {
                if (!unicode(s, &c)) {
                    return false;
                }
                if (c >= 0xd800 && c <= 0xdbff) {
                    unsigned low;
                    if (s->end - s->p < 6 || s->p[0] != '\\' || s->p[1] != 'u') {
                        return false;
                    }
                    s->p += 2;
                    if (!unicode(s, &low) || low < 0xdc00 || low > 0xdfff) {
                        return false;
                    }
                    c = 0x10000 + ((c - 0xd800) << 10) + (low - 0xdc00);
                } else if (c >= 0xdc00 && c <= 0xdfff) {
                    return false;
                }
            } else if (c == 'b') {
                c = 8;
            } else if (c == 'f') {
                c = 12;
            } else if (c == 'n') {
                c = 10;
            } else if (c == 'r') {
                c = 13;
            } else if (c == 't') {
                c = 9;
            } else if (c != '"' && c != '\\' && c != '/') {
                return false;
            }
        }
        if (!escaped && c >= 128 && !utf8(s, c)) {
            return false;
        }
        /* Contract identifiers/field names are ASCII. General strings need no
         * decoded storage; rejecting a non-ASCII metadata identifier is safer
         * than truncating it into another household's UUID. */
        if (out) {
            if (c > 127 || !c || n + 1 >= cap) {
                return false;
            }
            out[n++] = (char)c;
        }
    }
    return false;
}
static bool literal(Parser *s, const char *value)
{
    size_t n = strlen(value);
    if ((size_t)(s->end - s->p) < n || memcmp(s->p, value, n)) {
        return false;
    }
    s->p += n;
    return true;
}
static bool number(Parser *s, const char **start, size_t *length)
{
    const char *begin = s->p;
    if (s->p < s->end && *s->p == '-') {
        s->p++;
    }
    if (s->p == s->end) {
        return false;
    }
    if (*s->p == '0') {
        s->p++;
    } else {
        if (*s->p < '1' || *s->p > '9') {
            return false;
        }
        while (s->p < s->end && isdigit((unsigned char)*s->p)) {
            s->p++;
        }
    }
    if (s->p < s->end && *s->p == '.') {
        s->p++;
        if (s->p == s->end || !isdigit((unsigned char)*s->p)) {
            return false;
        }
        while (s->p < s->end && isdigit((unsigned char)*s->p)) {
            s->p++;
        }
    }
    if (s->p < s->end && (*s->p == 'e' || *s->p == 'E')) {
        s->p++;
        if (s->p < s->end && (*s->p == '+' || *s->p == '-')) {
            s->p++;
        }
        if (s->p == s->end || !isdigit((unsigned char)*s->p)) {
            return false;
        }
        while (s->p < s->end && isdigit((unsigned char)*s->p)) {
            s->p++;
        }
    }
    if (start) {
        *start = begin;
    }
    if (length) {
        *length = (size_t)(s->p - begin);
    }
    return true;
}
static bool integer(const char *start, size_t n, int64_t *value)
{
    if (!n || n >= 32) {
        return false;
    }
    char text[32];
    memcpy(text, start, n);
    text[n] = 0;
    char *end;
    errno = 0;
    long long parsed = strtoll(text, &end, 10);
    if (errno || *end) {
        return false;
    }
    *value = parsed;
    return true;
}
static bool value(Parser *, unsigned, int, const char *);
static bool object(Parser *s, unsigned depth, int context)
{
    s->p++;
    space(s);
    if (s->p < s->end && *s->p == '}') {
        s->p++;
        return true;
    }
    while (s->p < s->end) {
        char key[48];
        if (!string(s, key, sizeof key)) {
            return false;
        }
        space(s);
        if (s->p == s->end || *s->p++ != ':') {
            return false;
        }
        space(s);
        if (!value(s, depth + 1, context, key)) {
            return false;
        }
        space(s);
        if (s->p == s->end) {
            return false;
        }
        char c = *s->p++;
        if (c == '}') {
            return true;
        }
        if (c != ',') {
            return false;
        }
        space(s);
    }
    return false;
}
static bool array(Parser *s, unsigned depth, bool events, const char *section)
{
    s->p++;
    space(s);
    if (s->p < s->end && *s->p == ']') {
        s->p++;
        return true;
    }
    unsigned count = 0;
    while (s->p < s->end) {
        if (events && ++count > 64) {
            return false;
        }
        if (section) {
            s->row_seen = 0;
            s->row_section = section;
        }
        if (!value(s, depth + 1, section ? ROW : OTHER, "")) {
            return false;
        }
        space(s);
        if (s->p == s->end) {
            return false;
        }
        char c = *s->p++;
        if (c == ']') {
            return true;
        }
        if (c != ',') {
            return false;
        }
        space(s);
    }
    return false;
}
static bool value(Parser *s, unsigned depth, int context, const char *key)
{
    if (depth > DEPTH_MAX || s->p == s->end) {
        return false;
    }
    char c = *s->p;
    int child = OTHER;
    unsigned bit = 0;
    bool events = false;
    if (context == ROOT) {
        if (!strcmp(key, "schema_version")) {
            bit = 1;
        } else if (!strcmp(key, "home")) {
            bit = 2;
            child = HOME;
            if (c != '{') {
                return false;
            }
        } else if (!strcmp(key, "viewer")) {
            bit = 4;
            child = VIEWER;
            if (c != '{') {
                return false;
            }
        } else if (!strcmp(key, "revision")) {
            bit = 256;
        } else if (!strcmp(key, "server_time")) {
            bit = 512;
        } else {
            const char *arrays[] = {"people", "events", "chores", "shopping", "photos", "devices", "agents"};
            for (unsigned i = 0; i < 7; i++) {
                if (!strcmp(key, arrays[i])) {
                    bit = i < 5 ? 8u << i : 1024u << (i - 5);
                    if (c != '[') {
                        return false;
                    }
                    events = i == 1;
                }
            }
        }
        if (bit) {
            if (s->root_seen & bit) {
                return false;
            }
            s->root_seen |= bit;
        }
        /* Typed metadata must be checked before generic string/bool parsing,
         * otherwise a schema_version string could satisfy the required bit. */
        if (bit == 1 || bit == 256 || bit == 512) {
            const char *start;
            size_t n;
            int64_t integer_value;
            if (!number(s, &start, &n) || !integer(start, n, &integer_value)) {
                return false;
            }
            if (bit == 1) {
                return integer_value == 1;
            }
            if (bit == 256) {
                s->info->revision = integer_value;
                return integer_value >= 0;
            }
            s->info->server_time = integer_value;
            return true;
        }
    }
    if ((context == HOME && !strcmp(key, "id")) || (context == VIEWER && !strcmp(key, "user_id"))) {
        unsigned *seen = context == HOME ? &s->home_seen : &s->viewer_seen;
        if (*seen & 1) {
            return false;
        }
        *seen |= 1;
        if (c != '"' || !string(s, context == HOME ? s->info->home : s->info->viewer, 96)) {
            return false;
        }
        const char *id = context == HOME ? s->info->home : s->info->viewer;
        if (!*id) {
            return false;
        }
        for (; *id; id++) {
            if (!isalnum((unsigned char)*id) && *id != '-' && *id != '_') {
                return false;
            }
        }
        return true;
    }
    if (context == HOME && !strcmp(key, "demo")) {
        if (s->home_seen & 2) {
            return false;
        }
        s->home_seen |= 2;
        if (c == 't') {
            s->info->demo = true;
            return literal(s, "true");
        }
        if (c == 'f') {
            s->info->demo = false;
            return literal(s, "false");
        }
        return false;
    }
    if (context == ROW) {
        if (!*key) {
            if (c != '{') {
                return false;
            }
            child = ROW;
        } else if (!strcmp(key, "id")) {
            if (s->row_seen || c != '"' || !string(s, s->row_id, sizeof(s->row_id)) || !*s->row_id) {
                return false;
            }
            s->row_seen = 1;
            if (s->query_id && s->row_section && !strcmp(s->row_section, s->query_section) && !strcmp(s->row_id, s->query_id)) {
                s->found = true;
            }
            return true;
        }
    }
    if (c == '{') {
        return object(s, depth, child);
    }
    if (c == '[') {
        return array(s, depth, events, context == ROOT && s->query_section && !strcmp(key, s->query_section) ? key : NULL);
    }
    if (c == '"') {
        return string(s, NULL, 0);
    }
    if (c == 't') {
        return literal(s, "true");
    }
    if (c == 'f') {
        return literal(s, "false");
    }
    if (c == 'n') {
        return literal(s, "null");
    }
    return number(s, NULL, NULL);
}
static bool validate(const char *wire, size_t length, HQ_WireInfo *info, const char *section, const char *id, bool *found)
{
    if (!wire || !info || !length || length > WIRE_MAX) {
        return false;
    }
    memset(info, 0, sizeof *info);
    Parser s = {.p = wire, .end = wire + length, .info = info, .query_section = section, .query_id = id};
    space(&s);
    if (s.p == s.end || *s.p != '{' || !object(&s, 1, ROOT)) {
        return false;
    }
    space(&s);
    if (found) {
        *found = s.found;
    }
    return s.p == s.end && (s.root_seen & 251u) == 251u && ((s.home_seen & 1) || info->demo);
}
bool HQ_WireValidate(const char *wire, size_t length, HQ_WireInfo *info)
{
    return validate(wire, length, info, NULL, NULL, NULL);
}
bool HQ_WireHasRow(const char *wire, size_t length, const char *section, const char *id)
{
    if (!section || !id || !*id || strlen(id) >= 128) {
        return false;
    }
    const char *allowed[] = {"people", "events", "chores", "shopping", "photos", "devices", "agents"};
    bool known = false;
    for (unsigned i = 0; i < 7; i++) {
        if (!strcmp(section, allowed[i])) {
            known = true;
        }
    }
    if (!known) {
        return false;
    }
    HQ_WireInfo info;
    bool found = false;
    return validate(wire, length, &info, section, id, &found) && found;
}
