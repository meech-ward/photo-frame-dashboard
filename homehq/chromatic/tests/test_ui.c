#include "homehq.h"
#include "button.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static int64_t wall_ms;
static unsigned pressed, held, frames, pulses, commands, pending;
static bool visible, accept_command = true, photo_changed;
static char status[64] = "Demo", login_email[255], login_password[129];
static cJSON *incoming, *last_command;
static lv_color_t pixels[160 * 144];
static lv_obj_t *screen;
extern const lv_img_dsc_t homehq_photo_coast, homehq_photo_lake, homehq_photo_mountain;

int64_t esp_timer_get_time(void) { return wall_ms * 1000; }
void vTaskDelay(unsigned ticks) { wall_ms += ticks; lv_tick_inc(ticks); }
bool OSD_IsVisible(void) { return visible; }
void FPGA_Tx_PulseMenu(void) { assert(frames >= 2); ++pulses; visible = true; }
ButtonState_t Button_GetState(Button_t button)
{
    unsigned mask = 1u << button; bool state = (pressed & mask) != 0;
    pressed &= ~mask; return state ? kButtonState_Pressed : kButtonState_None;
}
bool Button_IsDown(Button_t button) { return (held & (1u << button)) != 0; }
void HQ_ServiceInit(void) {}
cJSON *HQ_ServicePoll(void) { cJSON *result = incoming; incoming = NULL; return result; }
bool HQ_ServiceCommand(const cJSON *command)
{
    ++commands; cJSON_Delete(last_command); last_command = cJSON_Duplicate(command, true);
    return accept_command;
}
void HQ_ServiceStatus(char *buffer, unsigned capacity, unsigned *out_pending)
{ snprintf(buffer, capacity, "%s", status); *out_pending = pending; }
bool HQ_ServiceConfigure(const cJSON *configuration) { (void)configuration; return true; }
bool HQ_ServiceSignIn(const char *email, const char *password)
{
    snprintf(login_email, sizeof(login_email), "%s", email);
    snprintf(login_password, sizeof(login_password), "%s", password);
    snprintf(status, sizeof(status), "Signing in"); return true;
}
bool HQ_ServiceLogout(void) { return pending == 0; }
void HQ_ServiceRefresh(void) {}
const lv_img_dsc_t *HQ_Photo(const cJSON *photo)
{
    const cJSON *asset = cJSON_GetObjectItemCaseSensitive(photo, "asset");
    const char *name = cJSON_IsString(asset) ? asset->valuestring : "";
    return strstr(name, "lake") ? &homehq_photo_lake : strstr(name, "mountain") ? &homehq_photo_mountain : &homehq_photo_coast;
}
void HQ_PhotoMaintain(const cJSON *photo) { (void)photo; }
bool HQ_PhotoChanged(void) { bool result = photo_changed; photo_changed = false; return result; }

static const cJSON *get(const cJSON *object, const char *key) { return cJSON_GetObjectItemCaseSensitive(object, key); }
static const char *str(const cJSON *object, const char *key)
{ const cJSON *value = get(object, key); return cJSON_IsString(value) ? value->valuestring : ""; }
static bool truth(const cJSON *object, const char *key) { return cJSON_IsTrue(get(object, key)); }
static const cJSON *table_row(const char *table, int index)
{ return cJSON_GetArrayItem(get(HomeHQ_Data(), table), index); }
static void flush(lv_disp_drv_t *driver, const lv_area_t *area, lv_color_t *colors)
{
    (void)colors; ++frames;
    assert(area->x1 == 0 && area->y1 == 0 && area->x2 == 159 && area->y2 == 143);
    lv_disp_flush_ready(driver);
}
static void maintain(void) { HomeHQ_Maintain(); lv_refr_now(NULL); }
static void input(const char *name) { HomeHQ_Input(name); maintain(); }
static void seek(const char *name)
{
    input("start");
    for (unsigned i = 0; i < 7 && strcmp(HomeHQ_Page(), name); ++i) input("right");
    assert(!strcmp(HomeHQ_Page(), name)); assert(!HomeHQ_Detail()[0]);
}
static void repeated(const char *name, unsigned count) { while (count--) input(name); }
static void transfer(cJSON *snapshot) { assert(!incoming); incoming = snapshot; maintain(); }
static void preview(const char *directory, const char *name)
{
    char path[1024]; snprintf(path, sizeof(path), "%s/%s.ppm", directory, name);
    FILE *file = fopen(path, "wb"); assert(file);
    fprintf(file, "P6\n160 144\n255\n");
    for (unsigned i = 0; i < 160 * 144; ++i) {
        lv_color32_t color = {.full = lv_color_to32(pixels[i])};
        const unsigned char rgb[] = {color.ch.red, color.ch.green, color.ch.blue};
        assert(fwrite(rgb, 1, sizeof(rgb), file) == sizeof(rgb));
    }
    assert(!fclose(file));
}
static bool has_label(lv_obj_t *root, const char *needle)
{
    if (lv_obj_check_type(root, &lv_label_class) && strstr(lv_label_get_text(root), needle)) return true;
    for (unsigned i = 0; i < lv_obj_get_child_cnt(root); ++i) if (has_label(lv_obj_get_child(root, i), needle)) return true;
    return false;
}
static lv_obj_t *find_label(lv_obj_t *root, const char *needle)
{
    if (lv_obj_check_type(root, &lv_label_class) && strstr(lv_label_get_text(root), needle)) return root;
    for (unsigned i = 0; i < lv_obj_get_child_cnt(root); ++i) {
        lv_obj_t *found = find_label(lv_obj_get_child(root, i), needle);
        if (found) return found;
    }
    return NULL;
}
static void assert_bounds(lv_obj_t *root)
{
    for (unsigned i = 0; i < lv_obj_get_child_cnt(root); ++i) {
        lv_obj_t *child = lv_obj_get_child(root, i);
        assert(lv_obj_get_x(child) >= 0 && lv_obj_get_y(child) >= 0);
        assert(lv_obj_get_x(child) + lv_obj_get_width(child) <= 160);
        assert(lv_obj_get_y(child) + lv_obj_get_height(child) <= 144);
        assert_bounds(child);
    }
}
static const char *bank[3][4] = {
    {"qwertyuiop", "asdfghjkl", "zxcvbnm@.", "0123456789"},
    {"QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM@.", "0123456789"},
    {"!@#$%^&*()", "-_=+[]{}\\|", ";:'\",.<>/?", "`~"}
};
static int kb_row, kb_col, kb_plane;
static void keyboard_move(int row, int column)
{
    while (kb_row < row) { input("down"); ++kb_row; int n = kb_row == 4 ? 4 : (int)strlen(bank[kb_plane][kb_row]); if (kb_col >= n) kb_col = n - 1; }
    while (kb_row > row) { input("up"); --kb_row; int n = kb_row == 4 ? 4 : (int)strlen(bank[kb_plane][kb_row]); if (kb_col >= n) kb_col = n - 1; }
    while (kb_col < column) { input("right"); ++kb_col; }
    while (kb_col > column) { input("left"); --kb_col; }
}
static void keyboard_action(int index) { keyboard_move(4, index); input("a"); }
static void type_character(char character)
{
    if (character == ' ') { keyboard_action(1); return; }
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
        for (int row = 0; row < 4; ++row) {
            const char *found = strchr(bank[kb_plane][row], character);
            if (found) { keyboard_move(row, (int)(found - bank[kb_plane][row])); input("a"); return; }
        }
        keyboard_action(2); kb_plane = (kb_plane + 1) % 3;
    }
    assert(!"printable character missing");
}
static void keyboard_begin(void) { input("a"); assert(!strcmp(HomeHQ_Detail(), "keyboard")); kb_row = kb_col = kb_plane = 0; }
static void type_string(const char *value) { while (*value) type_character(*value++); }

int main(int argc, char **argv)
{
    assert(argc == 2);
    lv_init();
    static lv_disp_draw_buf_t buffer; static lv_disp_drv_t driver;
    lv_disp_draw_buf_init(&buffer, pixels, NULL, 160 * 144); lv_disp_drv_init(&driver);
    driver.hor_res = 160; driver.ver_res = 144; driver.direct_mode = driver.full_refresh = 1;
    driver.draw_buf = &buffer; driver.flush_cb = flush;
    screen = lv_disp_get_scr_act(lv_disp_drv_register(&driver));
    HomeHQ_Show(screen); maintain();
    assert(frames >= 2 && pulses == 1 && visible);
    assert(has_label(screen, "Today"));
    assert(has_label(screen, "Wes") && has_label(screen, "Claudia") && has_label(screen, "Buzzsaw") && has_label(screen, "Skidmark"));
    visible = false; vTaskDelay(1100); maintain(); assert(pulses == 2 && visible);
    unsigned before = commands;
    const char *pages[] = {"today", "calendar", "chores", "shopping", "photos", "home", "agents"};
    for (unsigned i = 0; i < 7; ++i) {
        seek(pages[i]); assert_bounds(screen); preview(argv[1], pages[i]);
    }
    assert(commands == before);
    input("right"); assert(!strcmp(HomeHQ_Page(), "today"));
    input("left"); assert(!strcmp(HomeHQ_Page(), "agents"));
    pressed = 1u << kButton_Start; maintain(); assert(!strcmp(HomeHQ_Page(), "today"));

    seek("calendar"); input("down"); input("a"); assert(!strcmp(HomeHQ_Detail(), "event"));
    preview(argv[1], "event"); input("down"); assert(has_label(screen, "NOTES")); preview(argv[1], "event-notes");
    input("b"); assert(!HomeHQ_Detail()[0]);
    repeated("down", 100); int last = HomeHQ_Focus(); input("down"); assert(HomeHQ_Focus() == last);
    repeated("up", 100); assert(HomeHQ_Focus() == 0);

    seek("shopping"); input("a"); assert(truth(last_command, "done") && !strcmp(str(last_command, "kind"), "shopping"));
    input("a"); assert(!truth(last_command, "done"));
    accept_command = false; bool prior = truth(table_row("shopping", 0), "done"); input("a");
    assert(truth(table_row("shopping", 0), "done") == prior); accept_command = true;
    repeated("down", 2); char selected_id[128]; snprintf(selected_id, sizeof(selected_id), "%s", str(table_row("shopping", HomeHQ_Focus()), "id"));
    cJSON *changed = cJSON_Duplicate(HomeHQ_Data(), true);
    cJSON_InsertItemInArray((cJSON *)get(changed, "shopping"), 0, cJSON_Parse("{\"id\":\"new\",\"name\":\"Added above\",\"done\":false,\"version\":1}"));
    transfer(changed); assert(HomeHQ_Focus() == 3); input("a"); assert(!strcmp(str(last_command, "id"), selected_id));

    seek("chores"); repeated("down", 4); input("a"); assert(!strcmp(HomeHQ_Detail(), "chores"));
    input("a"); assert(!strcmp(HomeHQ_Detail(), "who")); input("down"); input("a");
    assert(!strcmp(str(last_command, "done_by"), "jordan")); assert(!strcmp(HomeHQ_Detail(), "chores"));
    preview(argv[1], "chore-detail"); input("right"); assert(!strcmp(HomeHQ_Detail(), "routine"));
    preview(argv[1], "routine"); input("a"); assert(has_label(screen, "Morning"));
    input("right"); input("down"); input("a"); input("down");
    lv_obj_t *long_instruction = find_label(screen, "Empty dishwasher");
    assert(long_instruction && lv_label_get_long_mode(long_instruction) == LV_LABEL_LONG_SCROLL_CIRCULAR);
    assert(lv_obj_get_style_anim_speed(long_instruction, LV_PART_MAIN) == 24);
    preview(argv[1], "chore-long-title");
    lv_color_t before_scroll[160 * 144]; memcpy(before_scroll, pixels, sizeof(pixels));
    for (unsigned step = 0; step < 40; ++step) { vTaskDelay(100); lv_timer_handler(); maintain(); }
    assert(memcmp(before_scroll, pixels, sizeof(pixels)) != 0);
    preview(argv[1], "chore-title-scroll");

    seek("home"); input("a"); assert(!strcmp(HomeHQ_Detail(), "device")); input("a");
    assert(!strcmp(str(last_command, "kind"), "device"));
    const cJSON *desired = get(last_command, "state"); assert(cJSON_GetArraySize(desired) == 1 && get(desired, "on"));
    preview(argv[1], "device"); input("b"); repeated("down", 3); input("a");
    before = commands; input("a"); assert(!strcmp(HomeHQ_Detail(), "confirm") && commands == before);
    preview(argv[1], "confirmation"); input("b"); assert(!strcmp(HomeHQ_Detail(), "device"));
    input("a"); input("a"); assert(commands == before + 1 && !strcmp(str(get(last_command, "state"), "state"), "open"));

    seek("photos"); assert(has_label(screen, "SAMPLE ART")); int first = HomeHQ_Focus(); vTaskDelay(12010); maintain(); assert(HomeHQ_Focus() != first);
    input("a"); int paused = HomeHQ_Focus(); vTaskDelay(24010); maintain(); assert(HomeHQ_Focus() == paused);
    assert(has_label(screen, "A Play")); input("a"); photo_changed = true; maintain(); assert(!photo_changed);
    seek("agents"); input("a"); assert(!strcmp(HomeHQ_Detail(), "agent"));
    assert(has_label(screen, "Weekly / all models") && !has_label(screen, "Weekly \xC2\xB7"));
    preview(argv[1], "agent-detail");

    /* DST repeats 1:00 AM locally. Next-event selection/countdown must still
     * see the event thirty UTC minutes ahead, at the later endpoint offset. */
    changed = cJSON_Duplicate(HomeHQ_Data(), true);
    cJSON_ReplaceItemInObject(changed, "server_time", cJSON_CreateNumber(1793512200));
    cJSON_ReplaceItemInObject((cJSON *)get(changed, "home"), "utc_offset_minutes", cJSON_CreateNumber(-240));
    cJSON_ReplaceItemInObject(changed, "events", cJSON_Parse("[{\"id\":\"dst\",\"start\":1793514000,\"end\":1793514600,\"start_offset_minutes\":-300,\"end_offset_minutes\":-300,\"title\":\"DST event\",\"people\":[\"alex\"],\"all_day\":false}]"));
    transfer(changed); seek("today"); assert(has_label(screen, "DST event") && has_label(screen, "30 minutes"));
    changed = cJSON_Duplicate(HomeHQ_Data(), true);
    cJSON_ReplaceItemInObject(cJSON_GetArrayItem((cJSON *)get(changed, "events"), 0), "title", cJSON_CreateString("Keep 20\xC2\xB0"));
    transfer(changed); assert(has_label(screen, "20\xC2\xB0"));

    /* A verified viewer owns both preferred chores and Anyone credit. */
    changed = cJSON_Parse(homehq_demo_json);
    cJSON_AddItemToObject(changed, "viewer", cJSON_Parse("{\"user_id\":\"member-one\",\"person_id\":\"maya\"}"));
    transfer(changed); seek("chores"); assert(HomeHQ_Focus() == 2);
    repeated("down", 2); input("a"); input("a"); assert(!strcmp(str(last_command, "done_by"), "maya"));
    input("select"); input("a"); assert(!strcmp(HomeHQ_Detail(), "logout")); preview(argv[1], "logout");
    pending = 1; maintain(); input("a"); assert(has_label(screen, "Connect to save")); pending = 0; maintain();

    /* An identity switch clears open confirmations and inherited selection. */
    changed = cJSON_Parse(homehq_demo_json); transfer(changed);
    assert(!strcmp(HomeHQ_Page(), "today") && !HomeHQ_Detail()[0]);
    input("select"); assert(!strcmp(HomeHQ_Detail(), "account")); preview(argv[1], "sign-in");
    keyboard_begin(); type_string("test@example.com"); keyboard_action(3);
    keyboard_begin(); char printable[96]; for (int i = 0; i < 95; ++i) printable[i] = (char)(32 + i); printable[95] = 0;
    type_string(printable); assert(!has_label(screen, " !\"#$")); preview(argv[1], "password-keyboard");
    keyboard_action(3); assert(!has_label(screen, " !\"#$")); input("a");
    assert(!strcmp(login_email, "test@example.com") && !strcmp(login_password, printable));
    assert(has_label(screen, "Signing in"));
    snprintf(status, sizeof(status), "Sign-in failed"); maintain();
    assert(has_label(screen, "Enter password") && !has_label(screen, printable));
    /* Abandoning a keyboard discards its transient edits. */
    repeated("up", 2); keyboard_begin(); type_string("abandoned@example.com"); input("b");
    assert(!has_label(screen, "abandoned"));
    assert_bounds(screen);
    cJSON_Delete(last_command);
    printf("PASS native navigation, desired-state writes, confirmation, identity, DST, slideshow and printable-ASCII masked sign-in (%u frames)\n", frames);
    return 0;
}
