#include "homehq_projection.h"
#include "homehq_wire.h"
#include <string.h>
#include <ctype.h>
#include <stdlib.h>

typedef struct { const char *wire; char *output; size_t length, capacity, read, write; const char *page; bool failed; } Project;
enum { ROOT, HOME, VIEWER, PEOPLE, EVENTS, CHORES, SHOPPING, PHOTOS, WEATHER, HOME_STATUS, AGENTS, METERS, DEVICES, STATE, RAW };
static const char *fields[] = {
    "schema_version revision server_time home viewer people events chores shopping photos weather home_status agents devices",
    "id utc_offset_minutes demo", "user_id person_id", "id name color home eta",
    "id start end start_offset_minutes end_offset_minutes all_day title people travel loc notes",
    "id who person_id routine title stars done version", "id name category store quantity done version",
    "id path asset caption place", "temp label sample", "temperature sample", "id name color meters week",
    "label used reset_minutes", "id name room type version on locked state", "on locked state", ""
};
static bool contains(const char *list, const char *key)
{
    size_t n = strlen(key);
    if (!n) return false;
    for (const char *p = list; *p;) {
        const char *end = strchr(p, ' '); size_t length = end ? (size_t)(end - p) : strlen(p);
        if (length == n && !memcmp(p, key, n)) return true;
        if (!end) break;
        p = end + 1;
    }
    return false;
}
static void whitespace(Project *p)
{ while (p->read < p->length && isspace((unsigned char)p->wire[p->read])) ++p->read; }
static void emit(Project *p, const char *text, size_t length)
{
    /* Every emitted value comes from an already-consumed source span, or a
     * shorter replacement. This invariant makes in-place compaction safe. */
    if (p->write + length > p->read || p->write + length > p->capacity) { p->failed = true; return; }
    /* NULL output is the measurement pass: consume the same spans and count
     * exactly the bytes that the emission pass will write, without allocation. */
    if (p->output) memmove(p->output + p->write, text, length);
    p->write += length;
}
static void character(Project *p, char value)
{ emit(p, &value, 1); }
static size_t quoted(Project *p)
{
    size_t start = p->read;
    if (p->read >= p->length || p->wire[p->read++] != '"') { p->failed = true; return start; }
    while (p->read < p->length) {
        unsigned char c = (unsigned char)p->wire[p->read++];
        if (c == '"') return start;
        if (c == '\\') { if (p->read >= p->length) break; ++p->read; }
        else if (c < 32) break;
    }
    p->failed = true; return start;
}
static void key_name(const char *wire, size_t start, size_t end, char *key, size_t capacity)
{
    size_t used = 0;
    for (size_t i = start + 1; i + 1 < end && used + 1 < capacity; ++i) {
        unsigned char c = (unsigned char)wire[i];
        if (c == '\\') {
            if (++i + 1 >= end) break;
            if (wire[i] == 'u' && i + 4 < end) {
                unsigned value = 0;
                for (unsigned j = 0; j < 4; ++j) {
                    unsigned char digit = (unsigned char)wire[++i];
                    value = value * 16 + (digit >= '0' && digit <= '9' ? digit - '0' : (digit | 32) - 'a' + 10);
                }
                c = value < 128 ? (unsigned char)value : 255;
            } else c = (unsigned char)wire[i];
        }
        key[used++] = (char)c;
    }
    key[used] = 0;
}
static void value(Project *p, int context, bool keep, unsigned depth);
static int root_context(const char *key)
{
    const char *names[] = {"", "home", "viewer", "people", "events", "chores", "shopping", "photos", "weather", "home_status", "agents", "", "devices"};
    for (int i = HOME; i <= DEVICES; ++i) if (names[i][0] && !strcmp(key, names[i])) return i;
    return RAW;
}
static bool active(const Project *p, int context)
{
    if (context == HOME || context == VIEWER || context == PEOPLE || context == RAW) return true;
    if (!strcmp(p->page, "today")) return context == EVENTS || context == WEATHER;
    if (!strcmp(p->page, "calendar")) return context == EVENTS;
    if (!strcmp(p->page, "chores")) return context == CHORES;
    if (!strcmp(p->page, "shopping")) return context == SHOPPING;
    if (!strcmp(p->page, "photos")) return context == PHOTOS;
    if (!strcmp(p->page, "home")) return context == DEVICES || context == HOME_STATUS;
    return context == AGENTS;
}
static void object(Project *p, int context, bool keep, unsigned depth)
{
    ++p->read; if (keep) character(p, '{'); bool first = true;
    whitespace(p);
    while (!p->failed && p->read < p->length && p->wire[p->read] != '}') {
        size_t start = quoted(p), end = p->read; char key[64]; key_name(p->wire, start, end, key, sizeof(key));
        whitespace(p); if (p->read >= p->length || p->wire[p->read++] != ':') { p->failed = true; break; }
        whitespace(p);
        bool selected = keep && (context == RAW || contains(fields[context], key));
        int child_context = context == ROOT ? root_context(key) : context == AGENTS && !strcmp(key, "meters") ? METERS : context == DEVICES && !strcmp(key, "state") ? STATE : RAW;
        bool inactive = context == ROOT && !active(p, child_context);
        bool array = p->read < p->length && p->wire[p->read] == '[';
        if (inactive && !array) selected = false;
        if (selected) {
            if (!first) character(p, ',');
            first = false;
            emit(p, p->wire + start, end - start); character(p, ':');
        }
        value(p, child_context, selected && !inactive, depth + 1);
        if (selected && inactive) emit(p, "[]", 2);
        whitespace(p);
        if (p->read < p->length && p->wire[p->read] == ',') { ++p->read; whitespace(p); }
        else break;
    }
    if (p->read >= p->length || p->wire[p->read++] != '}') p->failed = true;
    else if (keep) character(p, '}');
}
static void value(Project *p, int context, bool keep, unsigned depth)
{
    if (depth > 24 || p->read >= p->length) { p->failed = true; return; }
    char c = p->wire[p->read];
    if (c == '{') { object(p, context, keep, depth); return; }
    if (c == '[') {
        ++p->read; if (keep) character(p, '['); bool first = true; whitespace(p);
        while (!p->failed && p->read < p->length && p->wire[p->read] != ']') {
            if (keep && !first) character(p, ',');
            first = false;
            value(p, context, keep, depth + 1); whitespace(p);
            if (p->read < p->length && p->wire[p->read] == ',') { ++p->read; whitespace(p); }
            else break;
        }
        if (p->read >= p->length || p->wire[p->read++] != ']') p->failed = true;
        else if (keep) character(p, ']');
        return;
    }
    size_t start = p->read;
    if (c == '"') quoted(p);
    else while (p->read < p->length && !strchr(",}] \t\r\n", p->wire[p->read])) ++p->read;
    if (keep) emit(p, p->wire + start, p->read - start);
}
static bool valid_source(const char *wire, size_t length, const char *page)
{
    if (!wire || !page || !contains("today calendar chores shopping photos home agents", page)) return false;
    HQ_WireInfo info;
    return HQ_WireValidate(wire, length, &info);
}
static bool project(const char *wire, size_t length, const char *page, char *output, size_t capacity, size_t *written)
{
    Project p = {.wire = wire, .output = output, .length = length, .capacity = capacity, .page = page};
    whitespace(&p); value(&p, ROOT, true, 0); whitespace(&p);
    if (p.failed || p.read != length) return false;
    if (output) output[p.write] = 0;
    *written = p.write;
    return true;
}
bool HQ_ProjectWire(char *wire, size_t length, const char *page)
{
    if (!valid_source(wire, length, page)) return false;
    size_t written;
    return project(wire, length, page, wire, length, &written);
}
char *HQ_ProjectCopy(const char *canonical, size_t length, const char *page)
{
    if (!valid_source(canonical, length, page)) return NULL;
    size_t projected;
    if (!project(canonical, length, page, NULL, length, &projected)) return NULL;
    /* Physical WSS+HTTPS recovery left a largest block of 19,456 B. Copying
     * the whole 25 KB household failed despite adequate total heap; Today is
     * about 8.6 KB and Photos 2.6 KB, so allocate only the measured view. */
    char *output = malloc(projected + 1);
    if (!output) return NULL;
    size_t written;
    if (!project(canonical, length, page, output, projected, &written) || written != projected) {
        free(output); return NULL;
    }
    return output;
}
