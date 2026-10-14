/* Home HQ's native Chromatic view. This task alone owns LVGL and data: a
 * background request may transfer a new graph, but cannot redraw a half row. */
#include "homehq.h"
#include "src/misc/lv_txt.h"
#include "button.h"
#include "esp_timer.h"
#include "fpga_tx.h"
#include "osd.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#ifdef ESP_PLATFORM
#include "esp_heap_caps.h"
#include "esp_system.h"
#endif

#define W 160
#define H 144
#define PAPER 0xF2EEE6
#define CARD 0xFBF9F4
#define INK 0x111111
#define MUTE 0x69655D
#define LINE 0xD6CFC0
#define GREEN 0x00A36C
#define AMBER 0xFFB000
#define WHITE 0xFFFFFF
#define ID_SIZE 128
#define FOCUS_SLOTS 32

enum { TODAY, CALENDAR, CHORES, SHOPPING, PHOTOS, HOME, AGENTS, PAGE_COUNT };
enum { NONE, EVENT, PERSON_CHORES, WHO, ROUTINE, DEVICE, CONFIRM, AGENT, ACCOUNT, LOGOUT, KEYBOARD };
static const char *page_keys[] = {"today", "calendar", "chores", "shopping", "photos", "home", "agents"};
static const char *page_titles[] = {"Today", "Calendar", "Chores", "Shopping", "Photos", "Home", "Agents"};
static const char *detail_keys[] = {"", "event", "chores", "who", "routine", "device", "confirm", "agent", "account", "logout", "keyboard"};
static const char *routine_keys[] = {"morning", "after", "evening"};
static const char *routine_names[] = {"Morning", "After school", "Evening"};
typedef struct { char context[ID_SIZE], id[ID_SIZE]; } Focus;
static Focus focuses[FOCUS_SLOTS];
static lv_obj_t *panel;
static cJSON *data, *anyone, *routines, *account;
static int page, detail, routine = 1, detail_scroll;
static char person_id[ID_SIZE], event_id[ID_SIZE], device_id[ID_SIZE], agent_id[ID_SIZE], pending_chore[ID_SIZE];
static char notice[96], status_text[64];
static unsigned pending;
static bool dirty = true, playing = true, select_was_down, snapshot_waiting;
static bool displayed_photo;
static bool photo_request_cancelled;
static bool photo_hydration_waiting;
static uint8_t deferred_inputs[16];
static unsigned deferred_input_count;
static const char *deferred_input_names[] = {"up", "down", "left", "right", "a", "b", "start", "select"};
static char displayed_photo_path[106];
static char slideshow_id[ID_SIZE], slideshow_path[106];
static bool photo_dwell_started, photo_private_presented;
static int64_t photo_wait_until;
#define PHOTO_DWELL_US 12000000LL
#define PHOTO_WAIT_US 300000000LL
static int hydrated_page = TODAY;
static int64_t next_hydrate_retry;
static char retained_user[ID_SIZE], retained_person[ID_SIZE];
static int64_t retained_server_time;
static unsigned physical_edges[8], blocked_inputs;
static uint16_t held_buttons;
static int64_t clock_epoch, clock_started, next_menu_check, next_photo, notice_until;
static int last_minute = -1;
static const lv_img_dsc_t *photo_image;
static const char *device_action(const cJSON *row);
static char email[255], password[129], keyboard_text[255];
static int auth_focus, keyboard_field, keyboard_plane, keyboard_row, keyboard_column;
static bool signing_in, show_sign_in;
/* Lower/upper retain email punctuation; the symbol plane completes printable
 * ASCII. Credentials never pass through the JSON diagnostics snapshot. */
static const char *keyboard_rows[3][4] = {
    {"qwertyuiop", "asdfghjkl", "zxcvbnm@.", "0123456789"},
    {"QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM@.", "0123456789"},
    {"!@#$%^&*()", "-_=+[]{}\\|", ";:'\",.<>/?", "`~"}
};
static void boot_heap(const char *stage)
{
#ifdef ESP_PLATFORM
    /* Heap stages identify allocation failures without exposing configuration,
     * household data or credentials in the shared serial console. */
    printf("HQ boot heap=%lu largest=%lu stage=%s\n", (unsigned long)esp_get_free_heap_size(),
           (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT), stage);
#else
    (void)stage;
#endif
}
static cJSON *empty_data(void)
{ return cJSON_Parse("{\"schema_version\":1,\"home\":{},\"people\":[],\"events\":[],\"chores\":[],\"shopping\":[],\"photos\":[],\"devices\":[],\"agents\":[]}"); }

static const cJSON *field(const cJSON *object, const char *key)
{ return cJSON_GetObjectItemCaseSensitive(object, key); }
static const char *text(const cJSON *object, const char *key, const char *fallback)
{
    const cJSON *value = field(object, key);
    return cJSON_IsString(value) && value->valuestring ? value->valuestring : fallback;
}
static double number(const cJSON *object, const char *key, double fallback)
{
    const cJSON *value = field(object, key);
    return cJSON_IsNumber(value) ? value->valuedouble : fallback;
}
static bool boolean(const cJSON *object, const char *key, bool fallback)
{
    const cJSON *value = field(object, key);
    return cJSON_IsBool(value) ? cJSON_IsTrue(value) : fallback;
}
static void save_id(char *to, const char *from)
{ snprintf(to, ID_SIZE, "%s", from ? from : ""); }
static const cJSON *rows(const char *key)
{ return field(data, key); }
static const cJSON *find(const cJSON *array, const char *id)
{
    const cJSON *row;
    cJSON_ArrayForEach(row, array) if (!strcmp(text(row, "id", ""), id)) return row;
    return NULL;
}
static const cJSON *person(const char *id)
{ return !strcmp(id, "any") ? anyone : find(rows("people"), id); }
static uint32_t accent(const cJSON *row)
{
    const char *value = text(row, "color", "#111111");
    if (strlen(value) != 7 || value[0] != '#') return INK;
    char *end;
    unsigned long parsed = strtoul(value + 1, &end, 16);
    return *end ? INK : (uint32_t)parsed;
}
static int offset(void)
{ return (int)number(field(data, "home"), "utc_offset_minutes", 0); }
static int64_t epoch(void)
{ return clock_epoch ? clock_epoch + (esp_timer_get_time() - clock_started) / 1000000 : 0; }
static int64_t day_number(int64_t value, int zone)
{
    int64_t local = value + zone * 60;
    /* Division must floor before 1970 too; ordinary C division truncates. */
    return local >= 0 ? local / 86400 : (local - 86399) / 86400;
}
static void local_time(int64_t stamp, int zone, struct tm *out)
{
    time_t local = (time_t)(stamp + zone * 60);
    gmtime_r(&local, out);
}
static void clock_string(int64_t stamp, int zone, char *buffer, size_t size)
{
    struct tm tm;
    local_time(stamp, zone, &tm);
    snprintf(buffer, size, "%d:%02d%s", tm.tm_hour % 12 ? tm.tm_hour % 12 : 12, tm.tm_min, tm.tm_hour >= 12 ? "p" : "a");
}
static void day_string(int64_t stamp, int zone, char *buffer, size_t size)
{
    struct tm tm;
    local_time(stamp, zone, &tm);
    const char *days[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
    snprintf(buffer, size, "%s %d/%d", days[tm.tm_wday], tm.tm_mon + 1, tm.tm_mday);
}
static int default_routine(void)
{
    struct tm tm;
    local_time(epoch(), offset(), &tm);
    return tm.tm_hour < 11 ? 0 : tm.tm_hour < 17 ? 1 : 2;
}
static const cJSON *next_event(void)
{
    const cJSON *best = NULL, *row;
    int64_t now = epoch(), today = day_number(now, offset());
    cJSON_ArrayForEach(row, rows("events")) {
        int64_t start = (int64_t)number(row, "start", 0);
        int zone = (int)number(row, "start_offset_minutes", offset());
        /* UTC ordering/countdown survives the repeated local hour at DST end. */
        if (!boolean(row, "all_day", false) && start >= now && day_number(start, zone) == today &&
            (!best || start < (int64_t)number(best, "start", 0))) best = row;
    }
    return best;
}
static const cJSON *viewer_person(void)
{ return person(text(field(data, "viewer"), "person_id", "")); }
static bool signed_in(void)
{
    /* A cached viewer identifies the outbox owner, but does not prove that a
     * lost renewal token can authenticate. Keep that cache while offering login. */
    if (strstr(status_text, "Sign in again") || strstr(status_text, "Sign in to your home") ||
        strstr(status_text, "Sign-in failed") || strstr(status_text, "Signing in")) return false;
    return text(field(data, "viewer"), "user_id", "")[0] != 0;
}
static void clear_credentials(void)
{
    /* Clearing every buffer matters: an abandoned editor can otherwise retain
     * a password even after its shorter committed value has been submitted. */
    memset(email, 0, sizeof(email)); memset(password, 0, sizeof(password));
    memset(keyboard_text, 0, sizeof(keyboard_text));
}
static void masked(const char *value, char *output, size_t capacity)
{
    size_t length = strlen(value); if (length >= capacity) length = capacity - 1;
    memset(output, '*', length); output[length] = 0;
}
static int keyboard_columns(void)
{ return keyboard_row == 4 ? 4 : (int)strlen(keyboard_rows[keyboard_plane][keyboard_row]); }
static void keyboard_input(const char *button)
{
    if (!strcmp(button, "b")) { memset(keyboard_text, 0, sizeof(keyboard_text)); detail = ACCOUNT; }
    else if (!strcmp(button, "up") || !strcmp(button, "down")) {
        keyboard_row += !strcmp(button, "up") ? -1 : 1;
        if (keyboard_row < 0) keyboard_row = 0;
        if (keyboard_row > 4) keyboard_row = 4;
        if (keyboard_column >= keyboard_columns()) keyboard_column = keyboard_columns() - 1;
    } else if (!strcmp(button, "left") || !strcmp(button, "right")) {
        keyboard_column += !strcmp(button, "left") ? -1 : 1;
        if (keyboard_column < 0) keyboard_column = 0;
        if (keyboard_column >= keyboard_columns()) keyboard_column = keyboard_columns() - 1;
    } else if (!strcmp(button, "a")) {
        size_t length = strlen(keyboard_text), limit = keyboard_field ? 128 : 254;
        if (keyboard_row < 4) {
            if (length < limit) { keyboard_text[length] = keyboard_rows[keyboard_plane][keyboard_row][keyboard_column]; keyboard_text[length + 1] = 0; }
        } else if (keyboard_column == 0) { if (length) keyboard_text[length - 1] = 0; }
        else if (keyboard_column == 1) { if (length < limit) { keyboard_text[length] = ' '; keyboard_text[length + 1] = 0; } }
        else if (keyboard_column == 2) keyboard_plane = (keyboard_plane + 1) % 3;
        else {
            if (keyboard_field) snprintf(password, sizeof(password), "%.128s", keyboard_text);
            else snprintf(email, sizeof(email), "%s", keyboard_text);
            memset(keyboard_text, 0, sizeof(keyboard_text)); detail = ACCOUNT;
            auth_focus = keyboard_field ? 2 : 1;
        }
    }
    dirty = true;
}
static bool chore_matches(const cJSON *row)
{
    return !strcmp(text(row, "routine", "after"), routine_keys[routine]) &&
           !strcmp(text(row, "who", text(row, "person_id", "")), person_id);
}
static int count(void)
{
    if (detail == PERSON_CHORES) {
        int n = 0; const cJSON *row;
        cJSON_ArrayForEach(row, rows("chores")) if (chore_matches(row)) ++n;
        return n;
    }
    if (detail == WHO) return cJSON_GetArraySize(rows("people"));
    if (detail == ROUTINE) return 3;
    if (detail != NONE) return 0;
    if (page == CHORES) return cJSON_GetArraySize(rows("people")) + 1;
    if (page == HOME) return cJSON_GetArraySize(rows("devices")) + 1;
    const char *keys[] = {"", "events", "", "shopping", "photos", "", "agents"};
    return cJSON_GetArraySize(rows(keys[page]));
}
static const cJSON *row_at(int index)
{
    if (index < 0) return NULL;
    if (detail == PERSON_CHORES) {
        const cJSON *row;
        cJSON_ArrayForEach(row, rows("chores")) if (chore_matches(row) && index-- == 0) return row;
        return NULL;
    }
    if (detail == WHO) return cJSON_GetArrayItem(rows("people"), index);
    if (detail == ROUTINE) return cJSON_GetArrayItem(routines, index);
    if (detail != NONE) return NULL;
    if (page == CHORES) return index == cJSON_GetArraySize(rows("people")) ? anyone : cJSON_GetArrayItem(rows("people"), index);
    if (page == HOME) return index == cJSON_GetArraySize(rows("devices")) ? account : cJSON_GetArrayItem(rows("devices"), index);
    const char *keys[] = {"", "events", "", "shopping", "photos", "", "agents"};
    return cJSON_GetArrayItem(rows(keys[page]), index);
}
static Focus *focus_slot(void)
{
    char context[ID_SIZE];
    if (detail == PERSON_CHORES) snprintf(context, sizeof(context), "chores:%.100s:%d", person_id, routine);
    else snprintf(context, sizeof(context), "%s", detail == NONE ? page_keys[page] : detail_keys[detail]);
    Focus *empty = NULL;
    for (unsigned i = 0; i < FOCUS_SLOTS; ++i) {
        if (!strcmp(focuses[i].context, context)) return &focuses[i];
        if (!focuses[i].context[0] && !empty) empty = &focuses[i];
    }
    if (!empty) empty = &focuses[FOCUS_SLOTS - 1];
    save_id(empty->context, context); empty->id[0] = 0;
    return empty;
}
static int selection(void)
{
    Focus *focus = focus_slot();
    for (int i = 0; i < count(); ++i) if (!strcmp(text(row_at(i), "id", ""), focus->id)) return i;
    return 0;
}
static void align_selection(void)
{
    Focus *focus = focus_slot();
    for (int i = 0; i < count(); ++i) if (!strcmp(text(row_at(i), "id", ""), focus->id)) return;
    const cJSON *row = detail == NONE && page == CALENDAR ? next_event() : row_at(0);
    if (row) save_id(focus->id, text(row, "id", ""));
    else focus->id[0] = 0;
}
static const cJSON *selected(void)
{ return count() ? row_at(selection()) : NULL; }
static void follow_photo(const cJSON *photo, int64_t now)
{
    const char *id = text(photo, "id", ""), *path = text(photo, "path", "");
    if (strcmp(slideshow_id, id) || strcmp(slideshow_path, path)) {
        save_id(slideshow_id, id);
        snprintf(slideshow_path, sizeof(slideshow_path), "%s", path);
        photo_dwell_started = photo_private_presented = false;
        photo_wait_until = now + PHOTO_WAIT_US;
    }
}
static void photo_presented(const cJSON *photo, int64_t now)
{
    bool private_path = *text(photo, "path", "") != 0;
    bool private_ready = private_path && !HQ_PhotoIsFallback(photo);
    if (!private_path || private_ready || now >= photo_wait_until) {
        /* Eighty fresh 4 KiB requests for a maximum-size private PNG can exceed
         * the old 12-second slideshow timer and be canceled before completion.
         * Dwell starts on visible pixels; five minutes bounds fallback waiting
         * while pause/manual/page controls remain available throughout. */
        if (!photo_dwell_started || (private_ready && !photo_private_presented))
            next_photo = now + PHOTO_DWELL_US;
        photo_dwell_started = true;
        photo_private_presented = private_ready;
    }
}
static void move_selection(int amount)
{
    int index = selection() + amount, n = count();
    if (!n) {
        if (detail == EVENT) { detail_scroll = amount > 0 ? 1 : 0; dirty = true; }
        return;
    }
    if (index < 0) index = 0;
    if (index >= n) index = n - 1;
    save_id(focus_slot()->id, text(row_at(index), "id", ""));
    next_photo = esp_timer_get_time() + 12000000;
    dirty = true;
}
static void inform(const char *message)
{
    snprintf(notice, sizeof(notice), "%s", message);
    notice_until = esp_timer_get_time() + 2200000;
    dirty = true;
}
static void replace_value(cJSON *row, const char *key, const cJSON *value)
{
    cJSON *replacement = cJSON_Duplicate(value, true);
    if (field(row, key)) cJSON_ReplaceItemInObjectCaseSensitive(row, key, replacement);
    else cJSON_AddItemToObject(row, key, replacement);
}
static bool send_command(cJSON *command)
{
    bool accepted = command && HQ_ServiceCommand(command);
    if (accepted) {
        const char *kind = text(command, "kind", "");
        cJSON *row = (cJSON *)find(rows(!strcmp(kind, "chore") ? "chores" : !strcmp(kind, "shopping") ? "shopping" : "devices"), text(command, "id", ""));
        if (row) {
            /* Service owns durability/version anchoring. This local desired
             * state keeps a second physical press correct before its transfer. */
            if (!strcmp(kind, "device")) {
                cJSON *destination = (cJSON *)field(row, "state");
                if (!cJSON_IsObject(destination)) destination = row;
                const cJSON *value;
                cJSON_ArrayForEach(value, field(command, "state")) replace_value(destination, value->string, value);
            } else {
                replace_value(row, "done", field(command, "done"));
                if (field(command, "done_by")) replace_value(row, "done_by", field(command, "done_by"));
            }
        }
        inform(!strcmp(kind, "device") ? "Control queued" : boolean(command, "done", false) ? "Done" : "Undone");
    } else inform("Could not queue. Try again.");
    cJSON_Delete(command);
    return accepted;
}
static void complete(const cJSON *row, const char *kind, const char *by)
{
    if (!row) return;
    cJSON *command = cJSON_CreateObject();
    cJSON_AddStringToObject(command, "kind", kind);
    cJSON_AddStringToObject(command, "id", text(row, "id", ""));
    cJSON_AddBoolToObject(command, "done", !boolean(row, "done", false));
    cJSON_AddNumberToObject(command, "version", number(row, "version", 1));
    if (by) cJSON_AddStringToObject(command, "done_by", by);
    send_command(command);
}
static const cJSON *device_state(const cJSON *row)
{ const cJSON *state = field(row, "state"); return cJSON_IsObject(state) ? state : row; }
static void control(const cJSON *row)
{
    if (!row) return;
    const cJSON *state = device_state(row);
    const char *type = text(row, "type", "light");
    cJSON *command = cJSON_CreateObject(), *desired = cJSON_CreateObject();
    cJSON_AddStringToObject(command, "kind", "device");
    cJSON_AddStringToObject(command, "id", text(row, "id", ""));
    cJSON_AddNumberToObject(command, "version", number(row, "version", 1));
    /* A lamp action must preserve brightness; only the desired field crosses
     * the wire, so retrying it cannot overwrite another kind of device state. */
    if (!strcmp(type, "lock")) cJSON_AddBoolToObject(desired, "locked", !boolean(state, "locked", true));
    else if (!strcmp(type, "garage")) cJSON_AddStringToObject(desired, "state", !strcmp(text(state, "state", "closed"), "closed") ? "open" : "closed");
    else cJSON_AddBoolToObject(desired, "on", !boolean(state, "on", false));
    cJSON_AddItemToObject(command, "state", desired);
    send_command(command);
}

static void readable_glyphs(const char *value, const lv_font_t *face, char *output, size_t capacity)
{
    size_t used = 0;
    uint32_t cursor = 0;
    while (value[cursor] && used + 1 < capacity) {
        uint32_t start = cursor, codepoint = _lv_txt_encoded_next(value, &cursor);
        const char *replacement = NULL;
        /* These separators are common in synced calendar/usage text, but the
         * small resident fonts omit them. Preserve every glyph the font has;
         * authored punctuation falls back to familiar ASCII, never empty boxes. */
        lv_font_glyph_dsc_t glyph = {0};
        bool supported = codepoint == '\n' || codepoint == '\t' ||
                         (lv_font_get_glyph_dsc(face, &glyph, codepoint, 0) && !glyph.is_placeholder);
        if (!supported) {
            if (codepoint == 0x00B7 || codepoint == 0x2022) replacement = "/";
            else if (codepoint == 0x2018 || codepoint == 0x2019) replacement = "'";
            else if (codepoint == 0x201C || codepoint == 0x201D) replacement = "\"";
            else if (codepoint == 0x2013 || codepoint == 0x2014) replacement = "-";
            else if (codepoint == 0x2026) replacement = "...";
            else if (codepoint == 0x00A0) replacement = " ";
            else replacement = "?";
        }
        size_t length = replacement ? strlen(replacement) : cursor - start;
        if (length >= capacity - used) break;
        memcpy(output + used, replacement ? replacement : value + start, length);
        used += length;
    }
    output[used] = 0;
}
static lv_obj_t *label(const char *value, int x, int y, int width, int height, const lv_font_t *face, uint32_t color)
{
    lv_obj_t *object = lv_label_create(panel);
    lv_obj_set_pos(object, x, y);
    lv_obj_set_size(object, width, height);
    lv_label_set_long_mode(object, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_font(object, face, 0);
    lv_obj_set_style_text_color(object, lv_color_hex(color), 0);
    lv_obj_set_style_text_line_space(object, 1, 0);
    char readable[512];
    readable_glyphs(value ? value : "", face, readable, sizeof(readable));
    lv_label_set_text(object, readable);
    return object;
}
static lv_obj_t *box(int x, int y, int width, int height, uint32_t color, int radius, bool focused)
{
    lv_obj_t *object = lv_obj_create(panel);
    lv_obj_remove_style_all(object);
    lv_obj_set_pos(object, x, y);
    lv_obj_set_size(object, width, height);
    lv_obj_clear_flag(object, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(object, lv_color_hex(color), 0);
    lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(object, radius, 0);
    if (focused) {
        lv_obj_set_style_border_color(object, lv_color_hex(INK), 0);
        lv_obj_set_style_border_width(object, 2, 0);
    }
    return object;
}
static void bar(int x, int y, int width, int value, uint32_t color)
{
    if (value < 0) value = 0;
    if (value > 100) value = 100;
    box(x, y, width, 5, LINE, 2, false);
    if (value) box(x, y, width * value / 100, 5, color, 2, false);
}
static void checkbox(int x, int y, bool done, uint32_t color)
{
    box(x, y, 10, 10, done ? color : LINE, 2, false);
    if (done) label("+", x + 1, y - 1, 8, 12, &lv_font_montserrat_10, WHITE);
    else box(x + 2, y + 2, 6, 6, CARD, 0, false);
}
static void empty(const char *title, const char *subtitle)
{
    label(title, 8, 46, 144, 36, &lv_font_montserrat_14, INK);
    label(subtitle, 8, 87, 144, 32, &lv_font_montserrat_10, MUTE);
}
static const char *primary_label(void)
{
    const cJSON *row = selected();
    if (detail == PERSON_CHORES) return row ? boolean(row, "done", false) ? "Undo" : "Done" : "";
    if (detail == WHO || detail == ROUTINE) return "Use";
    if (detail == CONFIRM) return "Yes";
    if (detail == LOGOUT) return pending ? "" : "Yes";
    if (detail == ACCOUNT) return signed_in() ? "Sign out" : signing_in ? "" : auth_focus == 2 ? "Sign in" : "Edit";
    if (detail == KEYBOARD) return "Use";
    if (detail == DEVICE) return device_action(find(rows("devices"), device_id));
    if (detail != NONE) return "";
    if (page == SHOPPING) return row ? boolean(row, "done", false) ? "Undo" : "Get" : "";
    if (page == PHOTOS) return row ? playing ? "Pause" : "Play" : "";
    if (page == TODAY) return next_event() ? "Open" : "";
    return row ? "Open" : "";
}
static void header(void)
{
    const char *title = page_titles[page];
    if (detail == PERSON_CHORES) title = text(person(person_id), "name", "Chores");
    else if (detail == WHO) title = "Who did it?";
    else if (detail == ROUTINE) title = "Routine";
    else if (detail == EVENT) title = "Calendar";
    else if (detail == DEVICE || detail == CONFIRM) title = "Home control";
    else if (detail == AGENT) title = "Agent usage";
    else if (detail == ACCOUNT || detail == LOGOUT) title = "Your account";
    else if (detail == KEYBOARD) title = keyboard_field ? "Password" : "Email";
    label(title, 6, 4, 104, 19, &lv_font_montserrat_14, INK);
    char status[24];
    if (pending) snprintf(status, sizeof(status), "SEND %u", pending);
    else snprintf(status, sizeof(status), "%.8s", status_text[0] ? status_text : "DEMO");
    lv_obj_t *right = label(status, 109, 7, 45, 12, &lv_font_montserrat_10, strstr(status, "LIVE") || strstr(status, "live") ? GREEN : MUTE);
    lv_obj_set_style_text_align(right, LV_TEXT_ALIGN_RIGHT, 0);
    box(6, 24, 148, 1, LINE, 0, false);
    if (detail == NONE) for (int i = 0; i < PAGE_COUNT; ++i) box(114 + i * 6, 22, 4, 2, i == page ? INK : LINE, 0, false);
}
static void footer(void)
{
    box(0, 128, W, 16, PAPER, 0, false);
    box(6, 128, 148, 1, LINE, 0, false);
    char line[80];
    if (detail == KEYBOARD) snprintf(line, sizeof(line), "D-pad Move  A Use  B Cancel");
    else if (detail == PERSON_CHORES) snprintf(line, sizeof(line), "B Back   A %s   > Time", primary_label());
    else if (detail == EVENT) snprintf(line, sizeof(line), "B Back    Up/Down More");
    else if (detail != NONE) snprintf(line, sizeof(line), "B Back%s%s", primary_label()[0] ? "    A " : "", primary_label());
    else snprintf(line, sizeof(line), "< > Pages%s%s", primary_label()[0] ? "    A " : "", primary_label());
    label(line, 6, 131, 149, 12, &lv_font_montserrat_10, INK);
}
static void pager(int index, int total)
{
    char buffer[24];
    snprintf(buffer, sizeof(buffer), "%d/%d", total ? index + 1 : 0, total);
    lv_obj_t *object = label(buffer, 112, 29, 41, 12, &lv_font_montserrat_10, MUTE);
    lv_obj_set_style_text_align(object, LV_TEXT_ALIGN_RIGHT, 0);
}
static int window_start(int visible)
{ int index = selection(); return index / visible * visible; }
static void today_view(void)
{
    char buffer[128], clock[32], date[32];
    clock_string(epoch(), offset(), clock, sizeof(clock));
    label(clock, 6, 28, 95, 27, &lv_font_montserrat_20, INK);
    day_string(epoch(), offset(), date, sizeof(date));
    label(date, 7, 53, 85, 12, &lv_font_montserrat_10, MUTE);
    const cJSON *weather = field(data, "weather");
    snprintf(buffer, sizeof(buffer), "%.0f deg", number(weather, "temp", 0));
    lv_obj_t *object = label(buffer, 103, 31, 51, 17, &lv_font_montserrat_14, INK);
    lv_obj_set_style_text_align(object, LV_TEXT_ALIGN_RIGHT, 0);
    object = label(boolean(weather, "sample", false) ? "SAMPLE" : text(weather, "label", "Weather"), 103, 49, 51, 11, &lv_font_montserrat_10, MUTE);
    lv_obj_set_style_text_align(object, LV_TEXT_ALIGN_RIGHT, 0);
    const cJSON *event = next_event();
    const cJSON *ids = field(event, "people");
    const cJSON *pid = cJSON_GetArrayItem(ids, 0);
    uint32_t color = accent(person(cJSON_IsString(pid) ? pid->valuestring : "any"));
    uint32_t foreground = color == AMBER ? INK : WHITE;
    box(6, 68, 148, 35, color, 5, false);
    label(event ? text(event, "title", "Next event") : "Enjoy the quiet.", 11, 71, 138, 16, &lv_font_montserrat_12, foreground);
    if (event) {
        int gap = (int)(((int64_t)number(event, "start", epoch()) - epoch() + 59) / 60);
        int travel = (int)number(event, "travel", 0), leave = gap - travel;
        if (leave < 0) leave = 0;
        if (travel) snprintf(buffer, sizeof(buffer), "%d min / Leave %s%d%s", gap, leave ? "in " : "now", leave, leave ? "m" : "");
        else snprintf(buffer, sizeof(buffer), "Next in %d minutes", gap);
        if (travel && !leave) snprintf(buffer, sizeof(buffer), "%d min / Leave now", gap);
    } else snprintf(buffer, sizeof(buffer), "Nothing else scheduled today");
    label(buffer, 11, 88, 138, 12, &lv_font_montserrat_10, foreground);
    for (int i = 0; i < 4; ++i) {
        const cJSON *row = cJSON_GetArrayItem(rows("people"), i);
        if (!row) break;
        int x = 7 + (i % 2) * 77, y = 105 + (i / 2) * 11;
        box(x, y + 2, 2, 7, accent(row), 0, false);
        label(text(row, "name", ""), x + 4, y, 61, 11, &lv_font_montserrat_10, INK);
        /* Complete names carry more information than four clipped name/status
         * sentences. Green means home; gray away; amber means an ETA is known. */
        uint32_t state_color = boolean(row, "home", false) ? GREEN : number(row, "eta", 0) ? AMBER : MUTE;
        box(x + 66, y + 3, 5, 5, state_color, 3, false);
    }
}
static void calendar_view(void)
{
    char buffer[128], day[32], at[24];
    const cJSON *active = selected();
    day_string((int64_t)number(active, "start", epoch()), (int)number(active, "start_offset_minutes", offset()), day, sizeof(day));
    snprintf(buffer, sizeof(buffer), "%s / Week", day);
    label(buffer, 7, 29, 108, 12, &lv_font_montserrat_10, MUTE);
    pager(selection(), count());
    if (!count()) { empty("A clear calendar.", "Nothing scheduled this week."); return; }
    int first = window_start(2);
    for (int i = first; i < first + 2 && i < count(); ++i) {
        const cJSON *row = row_at(i), *pid = cJSON_GetArrayItem(field(row, "people"), 0);
        int y = 44 + (i - first) * 39;
        box(6, y, 148, 36, CARD, 5, i == selection());
        box(11, y + 6, 3, 24, accent(person(cJSON_IsString(pid) ? pid->valuestring : "any")), 1, false);
        label(text(row, "title", "Event"), 19, y + 5, 130, 15, &lv_font_montserrat_12, INK);
        int zone = (int)number(row, "start_offset_minutes", offset());
        day_string((int64_t)number(row, "start", epoch()), zone, day, sizeof(day));
        clock_string((int64_t)number(row, "start", epoch()), zone, at, sizeof(at));
        snprintf(buffer, sizeof(buffer), "%s / %s", day, boolean(row, "all_day", false) ? "All day" : at);
        label(buffer, 19, y + 21, 129, 12, &lv_font_montserrat_10, MUTE);
    }
}
static void event_view(void)
{
    const cJSON *row = find(rows("events"), event_id);
    if (!row) { empty("Event removed", "Your calendar changed."); return; }
    char buffer[256], day[32], begin[24], end[24];
    label(text(row, "title", "Event"), 7, 30, 146, 34, &lv_font_montserrat_14, INK);
    int zone = (int)number(row, "start_offset_minutes", offset());
    day_string((int64_t)number(row, "start", epoch()), zone, day, sizeof(day));
    clock_string((int64_t)number(row, "start", epoch()), zone, begin, sizeof(begin));
    clock_string((int64_t)number(row, "end", epoch()), (int)number(row, "end_offset_minutes", offset()), end, sizeof(end));
    snprintf(buffer, sizeof(buffer), "%s / %s", day, boolean(row, "all_day", false) ? "All day" : begin);
    label(buffer, 7, 65, 146, 12, &lv_font_montserrat_10, MUTE);
    if (detail_scroll) {
        label("NOTES", 7, 83, 146, 12, &lv_font_montserrat_10, MUTE);
        label(text(row, "notes", "No extra notes."), 7, 98, 146, 28, &lv_font_montserrat_10, INK);
    } else {
        size_t used = 0; buffer[0] = 0;
        const cJSON *pid;
        cJSON_ArrayForEach(pid, field(row, "people")) if (cJSON_IsString(pid) && used < sizeof(buffer) - 2) {
            int wrote = snprintf(buffer + used, sizeof(buffer) - used, "%s%s", used ? " + " : "", text(person(pid->valuestring), "name", "Family"));
            if (wrote < 0 || (size_t)wrote >= sizeof(buffer) - used) break;
            used += (size_t)wrote;
        }
        label(buffer, 7, 82, 146, 13, &lv_font_montserrat_10, INK);
        label(text(row, "loc", ""), 7, 98, 146, 13, &lv_font_montserrat_10, INK);
        snprintf(buffer, sizeof(buffer), "Ends %s / Travel %dm", end, (int)number(row, "travel", 0));
        label(buffer, 7, 113, 146, 12, &lv_font_montserrat_10, MUTE);
    }
}
static void chore_totals(const char *id, int *done, int *total)
{
    *done = *total = 0;
    const cJSON *row;
    cJSON_ArrayForEach(row, rows("chores")) if (!strcmp(text(row, "routine", "after"), routine_keys[routine]) &&
        (!id || !strcmp(text(row, "who", ""), id))) { ++*total; if (boolean(row, "done", false)) ++*done; }
}
static void chores_view(void)
{
    int completed, total; chore_totals(NULL, &completed, &total);
    char buffer[80];
    snprintf(buffer, sizeof(buffer), "%s / %d of %d", routine_names[routine], completed, total);
    label(buffer, 7, 29, 146, 12, &lv_font_montserrat_10, MUTE);
    int first = window_start(3);
    for (int i = first; i < first + 3 && i < count(); ++i) {
        const cJSON *row = row_at(i); int y = 44 + (i - first) * 27;
        box(6, y, 148, 25, CARD, 5, i == selection());
        chore_totals(text(row, "id", ""), &completed, &total);
        box(11, y + 7, 4, 11, accent(row), 2, false);
        label(text(row, "name", "Anyone"), 21, y + 5, 95, 17, &lv_font_montserrat_12, INK);
        snprintf(buffer, sizeof(buffer), "%d/%d", completed, total);
        label(buffer, 119, y + 7, 30, 13, &lv_font_montserrat_10, MUTE);
    }
}
static void person_chores_view(void)
{
    label(routine_names[routine], 7, 29, 98, 12, &lv_font_montserrat_10, MUTE);
    pager(selection(), count());
    if (!count()) { empty("All clear.", "No chores in this routine."); return; }
    uint32_t color = accent(person(person_id));
    int first = window_start(3);
    for (int i = first; i < first + 3 && i < count(); ++i) {
        const cJSON *row = row_at(i); int y = 44 + (i - first) * 27;
        box(6, y, 148, 25, CARD, 5, i == selection());
        checkbox(11, y + 8, boolean(row, "done", false), color);
        lv_obj_t *title = label(text(row, "title", "Chore"), 27, y + 5, 103, 16, &lv_font_montserrat_12, INK);
        if (i == selection()) {
            /* Bounded row width must not make an instruction unknowable. Only
             * the focused chore scrolls, leaving neighbouring rows still. */
            lv_label_set_long_mode(title, LV_LABEL_LONG_SCROLL_CIRCULAR);
            lv_obj_set_style_anim_speed(title, 24, 0);
        }
        char stars[12]; snprintf(stars, sizeof(stars), "%d*", (int)number(row, "stars", 0));
        if (number(row, "stars", 0)) label(stars, 132, y + 7, 17, 12, &lv_font_montserrat_10, MUTE);
    }
}
static void picker_view(void)
{
    label(detail == ROUTINE ? "Choose a time of day" : "Credit this family member", 7, 29, 146, 12, &lv_font_montserrat_10, MUTE);
    int first = window_start(3);
    for (int i = first; i < first + 3 && i < count(); ++i) {
        const cJSON *row = row_at(i); int y = 45 + (i - first) * 26;
        box(6, y, 148, 24, CARD, 5, i == selection());
        label(text(row, "name", ""), 15, y + 5, 130, 17, &lv_font_montserrat_12, INK);
    }
}
static void shopping_view(void)
{
    int remaining = 0; const cJSON *row;
    cJSON_ArrayForEach(row, rows("shopping")) if (!boolean(row, "done", false)) ++remaining;
    char buffer[160]; snprintf(buffer, sizeof(buffer), "%d to pick up", remaining);
    label(buffer, 7, 29, 105, 12, &lv_font_montserrat_10, MUTE);
    pager(selection(), count());
    if (!count()) { empty("Nothing needed.", "Add items in the companion."); return; }
    int first = window_start(2);
    for (int i = first; i < first + 2 && i < count(); ++i) {
        row = row_at(i); int y = 44 + (i - first) * 39;
        box(6, y, 148, 36, CARD, 5, i == selection());
        checkbox(11, y + 9, boolean(row, "done", false), INK);
        label(text(row, "name", "Item"), 27, y + 4, 105, 16, &lv_font_montserrat_12, INK);
        snprintf(buffer, sizeof(buffer), "x%d", (int)number(row, "quantity", 1));
        label(buffer, 132, y + 6, 17, 12, &lv_font_montserrat_10, MUTE);
        snprintf(buffer, sizeof(buffer), "%s / %s", text(row, "store", ""), text(row, "category", ""));
        label(buffer, 27, y + 21, 120, 12, &lv_font_montserrat_10, MUTE);
    }
}
static void photos_view(void)
{
    const cJSON *photo = selected();
    header();
    if (!photo) { empty("No photos yet.", "Add a memory in the companion."); return; }
    const lv_img_dsc_t *image = HQ_Photo(photo);
    if (image) {
        lv_obj_t *object = lv_img_create(panel);
        lv_img_set_src(object, image);
        /* The photo worker's 128x72 image avoids another full framebuffer.
         * Center it at authored pixels; stretching would hide useful detail. */
        lv_obj_set_pos(object, (W - image->header.w) / 2, 28);
    } else {
        box(16, 28, 128, 72, 0x194040, 3, false);
        label("Photo unavailable", 8, 49, 144, 25, &lv_font_montserrat_14, WHITE);
        label("Other screens still work.", 8, 78, 144, 20, &lv_font_montserrat_10, WHITE);
    }
    if (HQ_PhotoIsFallback(photo)) {
        box(19, 31, 79, 14, INK, 3, false);
        label("SAMPLE ART", 22, 33, 73, 12, &lv_font_montserrat_10, WHITE);
    }
    char buffer[24]; snprintf(buffer, sizeof(buffer), "%d/%d", selection() + 1, count());
    box(111, 31, 30, 14, INK, 3, false);
    label(buffer, 114, 33, 26, 12, &lv_font_montserrat_10, WHITE);
    label(text(photo, "caption", "A family memory"), 7, 103, 146, 12, &lv_font_montserrat_10, MUTE);
    label(text(photo, "place", ""), 7, 116, 146, 13, &lv_font_montserrat_12, INK);
}
static const char *device_value(const cJSON *row)
{
    const cJSON *state = device_state(row);
    if (!strcmp(text(row, "type", ""), "lock")) return boolean(state, "locked", true) ? "Locked" : "Unlocked";
    if (!strcmp(text(row, "type", ""), "garage")) return !strcmp(text(state, "state", "closed"), "closed") ? "Closed" : "Open";
    return boolean(state, "on", false) ? "On" : "Off";
}
static const char *device_action(const cJSON *row)
{
    const cJSON *state = device_state(row);
    if (!strcmp(text(row, "type", ""), "lock")) return boolean(state, "locked", true) ? "Unlock" : "Lock";
    if (!strcmp(text(row, "type", ""), "garage")) return !strcmp(text(state, "state", "closed"), "closed") ? "Open" : "Close";
    return boolean(state, "on", false) ? "Switch off" : "Switch on";
}
static void home_view(void)
{
    char buffer[64]; snprintf(buffer, sizeof(buffer), "SAMPLE / %.1f deg inside", number(field(data, "home_status"), "temperature", 20.5));
    label(buffer, 7, 29, 147, 12, &lv_font_montserrat_10, MUTE);
    int first = window_start(3);
    for (int i = first; i < first + 3 && i < count(); ++i) {
        const cJSON *row = row_at(i); int y = 44 + (i - first) * 27;
        bool is_account = !strcmp(text(row, "id", ""), "__account");
        box(6, y, 148, 25, CARD, 5, i == selection());
        label(text(row, "name", "Device"), 12, y + 5, 100, 17, &lv_font_montserrat_12, INK);
        lv_obj_t *object = label(is_account ? "Open" : device_value(row), 113, y + 7, 35, 13, &lv_font_montserrat_10, MUTE);
        lv_obj_set_style_text_align(object, LV_TEXT_ALIGN_RIGHT, 0);
    }
}
static void device_view(void)
{
    const cJSON *row = find(rows("devices"), device_id);
    if (!row) { empty("Device removed", "Your home list changed."); return; }
    char buffer[160]; snprintf(buffer, sizeof(buffer), "SAMPLE / %s", text(row, "room", "Home"));
    label(buffer, 7, 29, 147, 12, &lv_font_montserrat_10, MUTE);
    label(text(row, "name", "Device"), 7, 48, 146, 35, &lv_font_montserrat_14, INK);
    snprintf(buffer, sizeof(buffer), "Currently %s", device_value(row));
    label(buffer, 7, 82, 146, 13, &lv_font_montserrat_10, MUTE);
    if (detail == CONFIRM) {
        box(6, 98, 148, 27, INK, 5, false);
        snprintf(buffer, sizeof(buffer), "%s? A Yes / B Cancel", device_action(row));
        label(buffer, 11, 106, 138, 15, &lv_font_montserrat_10, WHITE);
    } else {
        label(device_action(row), 7, 99, 146, 17, &lv_font_montserrat_12, INK);
        label("Simulated state syncs to Home HQ", 7, 115, 146, 12, &lv_font_montserrat_10, MUTE);
    }
}
static void account_view(void)
{
    if (!signed_in()) {
        if (signing_in) { empty("Signing in...", "Connecting to your household."); return; }
        label(status_text[0] ? status_text : "Sign in to your household", 7, 28, 146, 12, &lv_font_montserrat_10, MUTE);
        for (int i = 0; i < 2; ++i) {
            int y = 42 + i * 28;
            box(6, y, 148, 26, CARD, 4, auth_focus == i);
            label(i ? "PASSWORD" : "EMAIL", 11, y + 3, 138, 11, &lv_font_montserrat_10, MUTE);
            char display[32];
            if (i) masked(password, display, sizeof(display));
            else snprintf(display, sizeof(display), "%.31s", email);
            label(display[0] ? display : i ? "Enter password" : "you@example.com", 11, y + 14, 138, 12, &lv_font_montserrat_10, display[0] ? INK : MUTE);
        }
        box(6, 100, 148, 25, auth_focus == 2 ? INK : CARD, 4, false);
        label("Sign in", 12, 105, 135, 17, &lv_font_montserrat_12, auth_focus == 2 ? WHITE : INK);
        return;
    }
    label("SIGNED IN", 7, 31, 146, 12, &lv_font_montserrat_10, MUTE);
    label(text(viewer_person(), "name", "Home owner"), 7, 48, 146, 35, &lv_font_montserrat_14, INK);
    if (detail == LOGOUT) {
        box(6, 92, 148, 32, INK, 5, false);
        label(pending ? "Save changes first." : "Sign out of Home HQ?", 11, 97, 138, 14, &lv_font_montserrat_12, WHITE);
        label(pending ? "Reconnect to send pending edits." : "A signs out / B cancels", 11, 112, 138, 12, &lv_font_montserrat_10, WHITE);
    } else {
        label("Your household stays in sync.", 7, 85, 146, 22, &lv_font_montserrat_10, MUTE);
        label("A signs out / B returns", 7, 110, 146, 14, &lv_font_montserrat_10, INK);
    }
}
static void keyboard_view(void)
{
    char buffer[64];
    snprintf(buffer, sizeof(buffer), "%s / %u of %d", keyboard_plane == 0 ? "abc" : keyboard_plane == 1 ? "ABC" : "Symbols", (unsigned)strlen(keyboard_text), keyboard_field ? 128 : 254);
    label(buffer, 7, 28, 146, 12, &lv_font_montserrat_10, MUTE);
    box(6, 41, 148, 16, CARD, 3, false);
    if (keyboard_field) masked(keyboard_text, buffer, sizeof(buffer));
    else snprintf(buffer, sizeof(buffer), "%.63s", strlen(keyboard_text) > 22 ? keyboard_text + strlen(keyboard_text) - 22 : keyboard_text);
    label(buffer[0] ? buffer : keyboard_field ? "Your password" : "Your email", 10, 43, 140, 13, &lv_font_montserrat_10, INK);
    for (int r = 0; r < 4; ++r) {
        const char *characters = keyboard_rows[keyboard_plane][r]; int n = (int)strlen(characters);
        for (int c = 0; c < n; ++c) {
            int x = 5 + c * 15, y = 60 + r * 14;
            bool focused = keyboard_row == r && keyboard_column == c;
            box(x, y, 14, 13, focused ? INK : CARD, 2, false);
            char character[] = {characters[c], 0};
            lv_obj_t *object = label(character, x + 1, y + 1, 12, 12, &lv_font_montserrat_10, focused ? WHITE : INK);
            lv_obj_set_style_text_align(object, LV_TEXT_ALIGN_CENTER, 0);
        }
    }
    const char *actions[] = {"Del", "Space", "Mode", "Save"};
    for (int c = 0; c < 4; ++c) {
        int x = 5 + c * 38; bool focused = keyboard_row == 4 && keyboard_column == c;
        box(x, 117, 36, 11, focused ? INK : CARD, 2, false);
        lv_obj_t *object = label(actions[c], x + 1, 117, 34, 12, &lv_font_montserrat_10, focused ? WHITE : INK);
        lv_obj_set_style_text_align(object, LV_TEXT_ALIGN_CENTER, 0);
    }
}
static void agents_view(void)
{
    label("SAMPLE USAGE / % used", 7, 29, 147, 12, &lv_font_montserrat_10, MUTE);
    if (!count()) { empty("A little breathing room.", "No usage cards configured."); return; }
    int first = window_start(3);
    for (int i = first; i < first + 3 && i < count(); ++i) {
        const cJSON *row = row_at(i), *meter = cJSON_GetArrayItem(field(row, "meters"), 0);
        int y = 44 + (i - first) * 27, used = (int)number(meter, "used", 0);
        box(6, y, 148, 25, CARD, 5, i == selection());
        label(text(row, "name", "Agent"), 12, y + 4, 81, 15, &lv_font_montserrat_12, INK);
        char buffer[24]; snprintf(buffer, sizeof(buffer), "%d%%", used);
        label(buffer, 115, y + 5, 32, 12, &lv_font_montserrat_10, INK);
        bar(92, y + 17, 54, used, accent(row));
    }
}
static void agent_view(void)
{
    const cJSON *row = find(rows("agents"), agent_id);
    if (!row) { empty("Usage card removed", "Your project changed."); return; }
    char buffer[128]; snprintf(buffer, sizeof(buffer), "%s / SAMPLE", text(row, "name", "Agent"));
    label(buffer, 7, 29, 146, 15, &lv_font_montserrat_12, INK);
    for (int i = 0; i < 2; ++i) {
        const cJSON *meter = cJSON_GetArrayItem(field(row, "meters"), i);
        if (!meter) break;
        int y = 47 + i * 34, used = (int)number(meter, "used", 0), mins = (int)number(meter, "reset_minutes", 0);
        label(text(meter, "label", "Usage"), 7, y, 107, 13, &lv_font_montserrat_10, MUTE);
        snprintf(buffer, sizeof(buffer), "%d%%", used);
        label(buffer, 121, y - 1, 33, 16, &lv_font_montserrat_12, accent(row));
        bar(7, y + 14, 146, used, accent(row));
        if (mins < 60) snprintf(buffer, sizeof(buffer), "Reset in %dm", mins);
        else if (mins < 1440) snprintf(buffer, sizeof(buffer), "Reset in %dh %dm", mins / 60, mins % 60);
        else snprintf(buffer, sizeof(buffer), "Reset in %dd %dh", mins / 1440, mins % 1440 / 60);
        label(buffer, 7, y + 21, 146, 12, &lv_font_montserrat_10, MUTE);
    }
    double peak = .01; const cJSON *value;
    cJSON_ArrayForEach(value, field(row, "week")) if (cJSON_IsNumber(value) && value->valuedouble > peak) peak = value->valuedouble;
    for (int i = 0; i < 7; ++i) {
        value = cJSON_GetArrayItem(field(row, "week"), i);
        if (!cJSON_IsNumber(value)) break;
        int height = (int)(value->valuedouble * 12 / peak); if (height < 1) height = 1;
        box(7 + i * 12, 125 - height, 8, height, accent(row), 0, false);
    }
    label("7 DAYS", 106, 115, 48, 12, &lv_font_montserrat_10, MUTE);
}
static void render(void)
{
    if (!panel) return;
    /* LVGL objects are rebuilt only when visible state changes. An idle
     * dashboard retains its complete frame instead of rasterizing each tick. */
    lv_obj_clean(panel);
    displayed_photo = false;
    if (page != PHOTOS || detail != NONE) HQ_PhotoMaintain(NULL);
    else HQ_PhotoRetireUnused(selected());
    lv_obj_set_style_bg_color(panel, lv_color_hex(PAPER), 0);
    if (detail == NONE && page == PHOTOS) {
        follow_photo(selected(), esp_timer_get_time());
        photos_view(); displayed_photo = true; photo_request_cancelled = false;
        snprintf(displayed_photo_path, sizeof(displayed_photo_path), "%s", text(selected(), "path", ""));
        photo_presented(selected(), esp_timer_get_time());
    }
    else {
        header();
        if (detail == EVENT) event_view();
        else if (detail == PERSON_CHORES) person_chores_view();
        else if (detail == WHO || detail == ROUTINE) picker_view();
        else if (detail == DEVICE || detail == CONFIRM) device_view();
        else if (detail == AGENT) agent_view();
        else if (detail == ACCOUNT || detail == LOGOUT) account_view();
        else if (detail == KEYBOARD) keyboard_view();
        else if (page == TODAY) today_view();
        else if (page == CALENDAR) calendar_view();
        else if (page == CHORES) chores_view();
        else if (page == SHOPPING) shopping_view();
        else if (page == HOME) home_view();
        else if (page == AGENTS) agents_view();
    }
    if (notice[0]) {
        box(6, 109, 148, 18, INK, 4, false);
        label(notice, 10, 113, 140, 12, &lv_font_montserrat_10, WHITE);
    }
    footer();
    dirty = false;
}

static bool hydrate(void);
static void cancel_departing_photo(void)
{
    if (!displayed_photo || photo_request_cancelled || (page == PHOTOS && detail == NONE)) return;
    /* Cancel decoder/TLS overlap before hydrating the larger destination page.
     * Reset retains active pixels until widget deletion, so an OOM keeps the
     * last useful frame rather than leaving LVGL with a freed image source. */
    HQ_PhotoReset();
    photo_request_cancelled = true;
}
static bool adopt_wire(char *wire)
{
    int64_t now = esp_timer_get_time();
    if (!snapshot_waiting) {
        /* A failed decode keeps these small identity anchors while the graph
         * is gone. Retrying must not impersonate an account switch and reset focus. */
        save_id(retained_user, text(field(data, "viewer"), "user_id", ""));
        save_id(retained_person, text(field(data, "viewer"), "person_id", ""));
        retained_server_time = (int64_t)number(data, "server_time", 0);
    }
    if (!wire) {
        free(wire); snapshot_waiting = true; next_hydrate_retry = now + 1000000;
        return false;
    }
    int target_page = page;
    char before[ID_SIZE], previous_person[ID_SIZE];
    save_id(before, retained_user); save_id(previous_person, retained_person);
    int64_t old_server = retained_server_time;
    /* The service transfers only the projected page bytes. Free the old graph
     * before decode so Photos never overlaps a calendar tree and decoder heap. */
    cJSON_Delete(data); data = NULL;
    cJSON *replacement = cJSON_Parse(wire);
    free(wire);
    if (!replacement) {
        boot_heap("snapshot parse failed");
        data = empty_data(); snapshot_waiting = true; next_hydrate_retry = now + 1000000;
        HQ_ServiceRefresh(); return false;
    }
    HQ_ServiceOverlay(replacement);
    const char *after = text(field(replacement, "viewer"), "user_id", "");
    bool identity_changed = strcmp(before, after) != 0;
    bool viewer_changed = strcmp(previous_person, text(field(replacement, "viewer"), "person_id", "")) != 0;
    int64_t new_server = (int64_t)number(replacement, "server_time", 0);
    if (identity_changed) {
        memset(focuses, 0, sizeof(focuses)); page = TODAY; detail = NONE; photo_image = NULL;
        clear_credentials(); if (after[0]) signing_in = false;
        if (show_sign_in && !after[0]) { page = HOME; detail = ACCOUNT; show_sign_in = false; }
        if (signing_in && !after[0]) { page = HOME; detail = ACCOUNT; }
    }
    data = replacement; hydrated_page = target_page; snapshot_waiting = false;
    if (new_server && new_server != old_server) { clock_epoch = new_server; clock_started = now; }
    if (detail != PERSON_CHORES && detail != WHO && detail != ROUTINE) routine = default_routine();
    if (identity_changed || viewer_changed) {
        const cJSON *viewer = viewer_person();
        if (viewer) { save_id(focuses[0].context, "chores"); save_id(focuses[0].id, text(viewer, "id", "")); }
    }
    dirty = true;
    /* An account transition can choose Today/Account after a different page
     * was projected. Hydrate that destination before aligning any row action. */
    if (page != hydrated_page) return hydrate();
    align_selection(); return true;
}
static bool hydrate(void)
{
    cancel_departing_photo();
    /* Physical Start during an active photo TLS request drove the heap minimum
     * to 48 bytes while the next page parsed. Reset cancels immediately, but
     * only the worker can release TLS; retain the old frame until it is idle. */
    if (HQ_PhotoWorkerBusy()) { photo_hydration_waiting = true; return false; }
    bool ready = adopt_wire(HQ_ServiceViewWire(page_keys[page]));
    if (ready) photo_hydration_waiting = false;
    return ready;
}

static void defer_input(const char *button)
{
    for (unsigned i = 0; i < sizeof(deferred_input_names) / sizeof(deferred_input_names[0]); ++i) {
        if (strcmp(button, deferred_input_names[i])) continue;
        /* Preserve a quick Start/Right/A sequence while canceled TLS unwinds.
         * Store bounded button codes, never caller-owned console string bytes. */
        if (deferred_input_count < sizeof(deferred_inputs)) deferred_inputs[deferred_input_count++] = (uint8_t)i;
        else ++blocked_inputs;
        return;
    }
}

static void replay_inputs(void)
{
    while (deferred_input_count && !photo_hydration_waiting && !snapshot_waiting) {
        unsigned input = deferred_inputs[0];
        --deferred_input_count;
        memmove(deferred_inputs, deferred_inputs + 1, deferred_input_count);
        HomeHQ_Input(deferred_input_names[input]);
    }
}

void HomeHQ_Input(const char *button)
{
    if (!button) return;
    if (photo_hydration_waiting) { defer_input(button); return; }
    if (!data || snapshot_waiting) { ++blocked_inputs; return; }
    /* A notice describes the last action. Carrying it into another page can
     * cover its confirmation or credentials, so the next deliberate key ends it. */
    notice[0] = 0;
    if (detail == KEYBOARD && strcmp(button, "start") && strcmp(button, "select")) { keyboard_input(button); return; }
    if (detail == ACCOUNT && !signed_in() && (!strcmp(button, "up") || !strcmp(button, "down"))) {
        if (!signing_in) {
            auth_focus += !strcmp(button, "up") ? -1 : 1;
            if (auth_focus < 0) auth_focus = 0;
            if (auth_focus > 2) auth_focus = 2;
            dirty = true;
        }
        return;
    }
    if (!strcmp(button, "up") || !strcmp(button, "down")) { move_selection(!strcmp(button, "up") ? -1 : 1); return; }
    if (!strcmp(button, "start")) { memset(keyboard_text, 0, sizeof(keyboard_text)); page = TODAY; detail = NONE; routine = default_routine(); }
    else if (!strcmp(button, "select")) { memset(keyboard_text, 0, sizeof(keyboard_text)); page = HOME; detail = ACCOUNT; }
    else if (!strcmp(button, "b")) {
        if (detail == WHO || detail == ROUTINE) detail = PERSON_CHORES;
        else if (detail == CONFIRM) detail = DEVICE;
        else if (detail == LOGOUT) detail = ACCOUNT;
        else detail = NONE;
    } else if (!strcmp(button, "left") || !strcmp(button, "right")) {
        if (detail == NONE) { page = (page + (!strcmp(button, "left") ? PAGE_COUNT - 1 : 1)) % PAGE_COUNT; routine = default_routine(); }
        else if (detail == PERSON_CHORES && !strcmp(button, "right")) detail = ROUTINE;
        else if (!strcmp(button, "left")) {
            if (detail == WHO || detail == ROUTINE) detail = PERSON_CHORES;
            else if (detail == CONFIRM) detail = DEVICE;
            else if (detail == LOGOUT) detail = ACCOUNT;
            else detail = NONE;
        }
    } else if (!strcmp(button, "a")) {
        const cJSON *row = selected();
        if (detail == NONE) {
            if (page == TODAY || page == CALENDAR) {
                row = page == TODAY ? next_event() : row;
                if (row) { save_id(event_id, text(row, "id", "")); detail = EVENT; detail_scroll = 0; }
            } else if (page == CHORES && row) { save_id(person_id, text(row, "id", "")); detail = PERSON_CHORES; }
            else if (page == SHOPPING && row) complete(row, "shopping", NULL);
            else if (page == PHOTOS && row) playing = !playing;
            else if (page == HOME && row) {
                if (!strcmp(text(row, "id", ""), "__account")) detail = ACCOUNT;
                else { save_id(device_id, text(row, "id", "")); detail = DEVICE; }
            } else if (page == AGENTS && row) { save_id(agent_id, text(row, "id", "")); detail = AGENT; }
        } else if (detail == PERSON_CHORES && row) {
            if (!strcmp(person_id, "any") && !boolean(row, "done", false)) {
                const cJSON *viewer = viewer_person();
                if (viewer) complete(row, "chore", text(viewer, "id", ""));
                else { save_id(pending_chore, text(row, "id", "")); detail = WHO; }
            } else complete(row, "chore", NULL);
        } else if (detail == WHO && row) {
            complete(find(rows("chores"), pending_chore), "chore", text(row, "id", ""));
            detail = PERSON_CHORES;
        } else if (detail == ROUTINE && row) {
            for (int i = 0; i < 3; ++i) if (!strcmp(text(row, "id", ""), routine_keys[i])) routine = i;
            detail = PERSON_CHORES;
        } else if (detail == DEVICE) {
            row = find(rows("devices"), device_id);
            if (row && (!strcmp(text(row, "type", ""), "lock") || !strcmp(text(row, "type", ""), "garage"))) detail = CONFIRM;
            else control(row);
        } else if (detail == CONFIRM) { control(find(rows("devices"), device_id)); detail = DEVICE; }
        else if (detail == ACCOUNT) {
            if (signed_in()) detail = LOGOUT;
            else if (!signing_in && auth_focus < 2) {
                keyboard_field = auth_focus; keyboard_plane = keyboard_row = keyboard_column = 0;
                snprintf(keyboard_text, sizeof(keyboard_text), "%s", keyboard_field ? password : email);
                detail = KEYBOARD;
            } else if (!signing_in) {
                /* Trim only email. Password case, punctuation and spaces are
                 * part of the credential and must reach Auth unchanged. */
                char *begin = email; while (*begin == ' ' || *begin == '\t') ++begin;
                if (begin != email) memmove(email, begin, strlen(begin) + 1);
                size_t length = strlen(email); while (length && (email[length - 1] == ' ' || email[length - 1] == '\t')) email[--length] = 0;
                char *at = strchr(email, '@');
                if (!at || at == email || !at[1] || strchr(at + 1, '@') || strpbrk(email, " \t\n\r")) { inform("Check your email address."); auth_focus = 0; }
                else if (!password[0]) { inform("Enter your password."); auth_focus = 1; }
                else if (HQ_ServiceSignIn(email, password)) { clear_credentials(); signing_in = true; }
                else inform("Unable to sign in. Try again.");
            }
        } else if (detail == LOGOUT) {
            if (pending) inform("Connect to save edits first.");
            else if (!HQ_ServiceLogout()) inform("Could not sign out. Try again.");
            else { detail = ACCOUNT; show_sign_in = true; inform("Signed out"); }
        }
    } else return;
    if (page != hydrated_page && !hydrate()) return;
    align_selection();
    next_photo = esp_timer_get_time() + 12000000;
    dirty = true;
}

void HomeHQ_Show(lv_obj_t *screen)
{
    if (panel) lv_obj_del(panel);
    panel = lv_obj_create(screen);
    lv_obj_remove_style_all(panel);
    lv_obj_set_pos(panel, 0, 0);
    lv_obj_set_size(panel, W, H);
    lv_obj_clear_flag(panel, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    if (!data) {
        /* The service stores JSON bytes, not a second household object graph.
         * Even two full 1,281-node graphs exhausted native ESP32 heap before
         * first paint. This task owns the only decoded household snapshot. */
        boot_heap("before service");
        HQ_ServiceInit();
        char *wire = HQ_ServicePollViewWire(page_keys[page]);
        boot_heap("before initial parse");
        data = wire ? cJSON_Parse(wire) : NULL;
        free(wire);
        boot_heap("after initial parse");
        snapshot_waiting = !data;
        hydrated_page = page;
        next_hydrate_retry = esp_timer_get_time() + 1000000;
        if (data) HQ_ServiceOverlay(data);
        else data = empty_data();
        anyone = cJSON_Parse("{\"id\":\"any\",\"name\":\"Anyone\",\"color\":\"#111111\"}");
        routines = cJSON_Parse("[{\"id\":\"morning\",\"name\":\"Morning\"},{\"id\":\"after\",\"name\":\"After school\"},{\"id\":\"evening\",\"name\":\"Evening\"}]");
        account = cJSON_Parse("{\"id\":\"__account\",\"name\":\"Your account\",\"type\":\"account\"}");
        clock_epoch = (int64_t)number(data, "server_time", 0);
        clock_started = esp_timer_get_time();
        routine = default_routine();
        const cJSON *viewer = viewer_person();
        if (viewer) { save_id(focuses[0].context, "chores"); save_id(focuses[0].id, text(viewer, "id", "")); }
    }
    align_selection();
    HQ_ServiceStatus(status_text, sizeof(status_text), &pending);
    render();
    boot_heap("after first render");
    /* qMenuInit requires two QSPI row-zero writes before the menu button can
     * expose the MCU overlay. This is the existing factory handshake. */
    for (unsigned frame = 0; frame < 2; ++frame) {
        lv_obj_invalidate(screen); lv_refr_now(NULL); vTaskDelay(pdMS_TO_TICKS(40));
    }
    next_menu_check = 0;
    next_photo = esp_timer_get_time() + 12000000;
    HomeHQ_Maintain();
}

void HomeHQ_Maintain(void)
{
    if (!panel) return;
    int64_t now = esp_timer_get_time();
    /* The cartridge boot ROM can close the overlay after MCU boot; reopening
     * it is independent of network state and retains the useful frame. */
    if (now >= next_menu_check) { next_menu_check = now + 1000000; if (!OSD_IsVisible()) FPGA_Tx_PulseMenu(); }
    const Button_t buttons[] = {kButton_Up, kButton_Down, kButton_Left, kButton_Right, kButton_A, kButton_B, kButton_Start};
    const char *names[] = {"up", "down", "left", "right", "a", "b", "start"};
    held_buttons = 0;
    for (unsigned i = 0; i < sizeof(buttons) / sizeof(buttons[0]); ++i) {
        if (Button_IsDown(buttons[i])) held_buttons |= (uint16_t)(1u << buttons[i]);
        if (Button_GetState(buttons[i]) == kButtonState_Pressed) { ++physical_edges[i]; HomeHQ_Input(names[i]); }
    }
    /* Select is absent from the FPGA's ordinary consumed-edge mask. Sample
     * its held state once per transition instead of reopening on every tick. */
    bool select_down = Button_IsDown(kButton_Select);
    if (select_down) held_buttons |= (uint16_t)(1u << kButton_Select);
    if (select_down && !select_was_down) { ++physical_edges[7]; HomeHQ_Input("select"); }
    select_was_down = select_down;
    if (photo_hydration_waiting) {
        if (HQ_PhotoWorkerBusy() || !hydrate()) return;
    }
    /* A current page's mailbox can wait too: polling allocates projected bytes
     * before parsing, and must not compete with an active photo transport. */
    char *wire = HQ_PhotoWorkerBusy() ? NULL : HQ_ServicePollViewWire(page_keys[page]);
    if (wire && !adopt_wire(wire)) return;
    if (snapshot_waiting && now >= next_hydrate_retry && !hydrate()) return;
    replay_inputs();
    if (photo_hydration_waiting) return;
    char next_status[64]; unsigned next_pending;
    HQ_ServiceStatus(next_status, sizeof(next_status), &next_pending);
    if (strcmp(status_text, next_status) || next_pending != pending) {
        snprintf(status_text, sizeof(status_text), "%s", next_status); pending = next_pending; dirty = true;
        if (signing_in && (strstr(status_text, "Sign-in failed") || strstr(status_text, "Sign in again") || strstr(status_text, "Sign in to your home"))) signing_in = false;
        if ((strstr(status_text, "Sign in again") || strstr(status_text, "Sign in to your home")) && detail != KEYBOARD) { page = HOME; detail = ACCOUNT; }
    }
    if (!snapshot_waiting && page != hydrated_page && !hydrate()) return;
    int minute = (int)(epoch() / 60);
    if (minute != last_minute) {
        last_minute = minute;
        if (detail != PERSON_CHORES && detail != WHO && detail != ROUTINE) routine = default_routine();
        dirty = true;
    }
    if (notice[0] && now >= notice_until) { notice[0] = 0; dirty = true; }
    if (page == PHOTOS && detail == NONE) {
        follow_photo(selected(), now);
        if (playing && count() && photo_dwell_started && now >= next_photo) {
            save_id(focus_slot()->id, text(row_at((selection() + 1) % count()), "id", ""));
            next_photo = now + 12000000; dirty = true;
            follow_photo(selected(), now);
        }
        const cJSON *photo = selected();
        if (displayed_photo && strcmp(displayed_photo_path, text(photo, "path", ""))) {
            /* Give back the old 18 KiB before queuing its replacement. The
             * release-only seam preserves a matching pending worker result;
             * this runs after successful hydration on the sole LVGL task. */
            lv_obj_clean(panel);
            displayed_photo = false;
            HQ_PhotoRetireUnused(photo);
            photo_image = NULL;
            dirty = true;
        }
        HQ_PhotoMaintain(photo);
        const lv_img_dsc_t *image = HQ_Photo(photo);
        if (image != photo_image || HQ_PhotoChanged()) { photo_image = image; dirty = true; }
        if (!photo_dwell_started && now >= photo_wait_until) dirty = true;
    } else {
        slideshow_id[0] = slideshow_path[0] = 0;
        photo_dwell_started = photo_private_presented = false;
    }
    if (dirty && !snapshot_waiting) render();
    if (!displayed_photo) { HQ_PhotoMaintain(NULL); photo_image = NULL; }
}

const char *HomeHQ_Page(void) { return page_keys[page]; }
const char *HomeHQ_Detail(void) { return detail_keys[detail]; }
int HomeHQ_Focus(void) { return detail == ACCOUNT && !signed_in() ? auth_focus : detail == KEYBOARD ? keyboard_row * 10 + keyboard_column : selection(); }
const cJSON *HomeHQ_Data(void) { return data; }
void HomeHQ_InputDiagnostics(cJSON *object)
{
    if (!object) return;
    const char *keys[] = {"physical_up", "physical_down", "physical_left", "physical_right", "physical_a", "physical_b", "physical_start", "physical_select"};
    for (unsigned i = 0; i < 8; ++i) cJSON_AddNumberToObject(object, keys[i], physical_edges[i]);
    cJSON_AddNumberToObject(object, "held_buttons", held_buttons);
    cJSON_AddNumberToObject(object, "blocked_inputs", blocked_inputs);
    cJSON_AddBoolToObject(object, "snapshot_waiting", snapshot_waiting);
    cJSON_AddStringToObject(object, "hydrated_page", page_keys[hydrated_page]);
}
