#include "homehq.h"
#include "homehq_projection.h"
#include "homehq_wire.h"
#include "button.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static int64_t wall_ms;
static unsigned pressed, held, frames, pulses, commands, pending;
static bool visible, accept_command = true, photo_changed;
static bool fail_next_view_poll;
static bool fail_next_view_hydration, photo_reset_pending;
static bool photo_worker_busy;
static unsigned view_hydrations, view_polls;
static unsigned photo_resets, photo_retires;
static char photo_loaded_path[106], photo_pending_path[106], photo_requested_path[106];
static lv_img_dsc_t private_photo;
static char status[64] = "Demo", login_email[255], login_password[129];
static cJSON *last_command;
static cJSON *queued_commands;
static char *incoming_wire;
static char *canonical_wire;
static unsigned overlays, refresh_requests;
typedef union { struct { size_t size; bool node; } allocation; long double alignment; } Allocation;
static size_t json_bytes, peak_json_bytes;
static unsigned json_nodes, peak_json_nodes, fixture_nodes, fail_node_after;
static void *json_allocate(size_t size)
{
    bool node = size == sizeof(cJSON);
    if (node && fail_node_after && --fail_node_after == 0) return NULL;
    Allocation *memory = malloc(sizeof(*memory) + size); if (!memory) return NULL;
    memory->allocation.size = size; memory->allocation.node = node;
    json_bytes += size; if (node) ++json_nodes;
    if (json_bytes > peak_json_bytes) peak_json_bytes = json_bytes;
    if (json_nodes > peak_json_nodes) peak_json_nodes = json_nodes;
    return memory + 1;
}
static void json_release(void *pointer)
{
    if (!pointer) return;
    Allocation *memory = (Allocation *)pointer - 1;
    assert(json_bytes >= memory->allocation.size);
    json_bytes -= memory->allocation.size; if (memory->allocation.node) { assert(json_nodes); --json_nodes; }
    free(memory);
}
static unsigned nodes_in(const cJSON *node)
{
    if (!node) return 0;
    unsigned count = 1; const cJSON *child;
    cJSON_ArrayForEach(child, node) count += nodes_in(child);
    return count;
}
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
void HQ_ServiceInit(void)
{
    if (!canonical_wire) canonical_wire = strdup(homehq_demo_json);
    if (!incoming_wire) incoming_wire = strdup(canonical_wire);
    if (!queued_commands) queued_commands = cJSON_CreateArray();
}
cJSON *HQ_ServicePoll(void) { assert(!"UI must use the wire transfer"); return NULL; }
char *HQ_ServicePollWire(void) { char *result = incoming_wire; incoming_wire = NULL; return result; }
char *HQ_ServicePollViewWire(const char *page)
{
    assert(!photo_worker_busy); ++view_polls;
    if (!incoming_wire) return NULL;
    if (fail_next_view_poll) { fail_next_view_poll = false; return NULL; }
    char *view = HQ_ProjectCopy(incoming_wire, strlen(incoming_wire), page);
    if (view) { free(incoming_wire); incoming_wire = NULL; }
    return view;
}
char *HQ_ServiceViewWire(const char *page)
{
    assert(!photo_worker_busy); ++view_hydrations;
    if (fail_next_view_hydration) { fail_next_view_hydration = false; return NULL; }
    char *wire = strdup(canonical_wire);
    if (!HQ_ProjectWire(wire, strlen(wire), page)) { free(wire); return NULL; }
    return wire;
}
static void overlay_value(cJSON *row, const char *key, const cJSON *value)
{
    cJSON *copy = cJSON_Duplicate(value, true);
    if (cJSON_GetObjectItemCaseSensitive(row, key)) cJSON_ReplaceItemInObjectCaseSensitive(row, key, copy);
    else cJSON_AddItemToObject(row, key, copy);
}
void HQ_ServiceOverlay(cJSON *graph)
{
    assert(graph); ++overlays;
    const cJSON *command;
    cJSON_ArrayForEach(command, queued_commands) {
        const char *kind = cJSON_GetObjectItemCaseSensitive(command, "kind")->valuestring;
        const char *id = cJSON_GetObjectItemCaseSensitive(command, "id")->valuestring;
        cJSON *row;
        cJSON_ArrayForEach(row, cJSON_GetObjectItemCaseSensitive(graph, !strcmp(kind, "chore") ? "chores" : !strcmp(kind, "shopping") ? "shopping" : "devices")) {
            const cJSON *key = cJSON_GetObjectItemCaseSensitive(row, "id");
            if (!cJSON_IsString(key) || strcmp(key->valuestring, id)) continue;
            if (!strcmp(kind, "device")) {
                cJSON *state = cJSON_GetObjectItemCaseSensitive(row, "state");
                if (!cJSON_IsObject(state)) state = row;
                const cJSON *value;
                cJSON_ArrayForEach(value, cJSON_GetObjectItemCaseSensitive(command, "state")) overlay_value(state, value->string, value);
            } else {
                overlay_value(row, "done", cJSON_GetObjectItemCaseSensitive(command, "done"));
                const cJSON *by = cJSON_GetObjectItemCaseSensitive(command, "done_by");
                if (by) overlay_value(row, "done_by", by);
            }
        }
    }
}
bool HQ_ServiceCommand(const cJSON *command)
{
    ++commands; cJSON_Delete(last_command); last_command = cJSON_Duplicate(command, true);
    if (accept_command) {
        const cJSON *id = cJSON_GetObjectItemCaseSensitive(command, "id"), *kind = cJSON_GetObjectItemCaseSensitive(command, "kind");
        int replace = -1;
        for (int i = 0; i < cJSON_GetArraySize(queued_commands); ++i) {
            cJSON *old = cJSON_GetArrayItem(queued_commands, i);
            if (!strcmp(cJSON_GetObjectItemCaseSensitive(old, "id")->valuestring, id->valuestring) &&
                !strcmp(cJSON_GetObjectItemCaseSensitive(old, "kind")->valuestring, kind->valuestring)) replace = i;
        }
        if (replace >= 0) cJSON_ReplaceItemInArray(queued_commands, replace, cJSON_Duplicate(command, true));
        else cJSON_AddItemToArray(queued_commands, cJSON_Duplicate(command, true));
    }
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
void HQ_ServiceRefresh(void) { ++refresh_requests; }
const lv_img_dsc_t *HQ_Photo(const cJSON *photo)
{
    const cJSON *path = cJSON_GetObjectItemCaseSensitive(photo, "path");
    if (photo_loaded_path[0] && cJSON_IsString(path) && !strcmp(path->valuestring, photo_loaded_path)) return &private_photo;
    const cJSON *asset = cJSON_GetObjectItemCaseSensitive(photo, "asset");
    const char *name = cJSON_IsString(asset) ? asset->valuestring : "";
    return strstr(name, "lake") ? &homehq_photo_lake : strstr(name, "mountain") ? &homehq_photo_mountain : &homehq_photo_coast;
}
static bool has_image(const lv_obj_t *object)
{
    if (lv_obj_check_type(object, &lv_img_class)) return true;
    for (unsigned i = 0; i < lv_obj_get_child_cnt(object); ++i) if (has_image(lv_obj_get_child(object, i))) return true;
    return false;
}
bool HQ_PhotoIsFallback(const cJSON *photo) { return HQ_Photo(photo) != &private_photo; }
void HQ_PhotoRetireUnused(const cJSON *photo)
{
    assert(!screen || !has_image(screen));
    const cJSON *path = cJSON_GetObjectItemCaseSensitive(photo, "path");
    if (photo_loaded_path[0] && (!cJSON_IsString(path) || strcmp(path->valuestring, photo_loaded_path))) {
        ++photo_retires; photo_loaded_path[0] = 0; photo_changed = true;
    }
}
void HQ_PhotoMaintain(const cJSON *photo)
{
    const cJSON *path = cJSON_GetObjectItemCaseSensitive(photo, "path");
    if (!photo) assert(!screen || !has_image(screen));
    if (!photo || photo_reset_pending) { photo_loaded_path[0] = 0; photo_reset_pending = false; }
    snprintf(photo_requested_path, sizeof(photo_requested_path), "%s", cJSON_IsString(path) ? path->valuestring : "");
    if (photo_pending_path[0] && !strcmp(photo_pending_path, photo_requested_path)) {
        snprintf(photo_loaded_path, sizeof(photo_loaded_path), "%s", photo_pending_path);
        photo_pending_path[0] = 0; photo_changed = true;
    }
}
void HQ_PhotoReset(void)
{
    ++photo_resets; photo_pending_path[0] = photo_requested_path[0] = 0; photo_reset_pending = true;
}
bool HQ_PhotoChanged(void) { bool result = photo_changed; photo_changed = false; return result; }
bool HQ_PhotoWorkerBusy(void) { return photo_worker_busy; }

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
static void transfer(cJSON *snapshot)
{
    assert(!incoming_wire);
    char *encoded = cJSON_PrintUnformatted(snapshot); assert(encoded);
    HQ_WireInfo before = {0}, after = {0};
    assert(HQ_WireValidate(canonical_wire, strlen(canonical_wire), &before));
    assert(HQ_WireValidate(encoded, strlen(encoded), &after));
    if (strcmp(before.viewer, after.viewer)) {
        cJSON_Delete(queued_commands); queued_commands = cJSON_CreateArray();
    }
    incoming_wire = strdup(encoded); assert(incoming_wire);
    free(canonical_wire); canonical_wire = strdup(encoded); assert(canonical_wire);
    cJSON_free(encoded); cJSON_Delete(snapshot);
    /* Fixture construction is test setup, not service retention. Reset after
     * releasing it; parsing a mailbox must never overlap two UI full graphs. */
    peak_json_bytes = json_bytes; peak_json_nodes = json_nodes;
    maintain();
    assert(peak_json_nodes <= fixture_nodes + 100);
}
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
    cJSON_Hooks hooks = {.malloc_fn = json_allocate, .free_fn = json_release};
    cJSON_InitHooks(&hooks);
    cJSON *full_fixture = cJSON_Parse(homehq_demo_json); assert(full_fixture);
    fixture_nodes = nodes_in(full_fixture); cJSON_Delete(full_fixture);
    peak_json_nodes = json_nodes; peak_json_bytes = json_bytes;
    lv_init();
    private_photo = homehq_photo_coast;
    static lv_disp_draw_buf_t buffer; static lv_disp_drv_t driver;
    lv_disp_draw_buf_init(&buffer, pixels, NULL, 160 * 144); lv_disp_drv_init(&driver);
    driver.hor_res = 160; driver.ver_res = 144; driver.direct_mode = driver.full_refresh = 1;
    driver.draw_buf = &buffer; driver.flush_cb = flush;
    screen = lv_disp_get_scr_act(lv_disp_drv_register(&driver));
    HomeHQ_Show(screen); maintain();
    /* On-device overlapping 1,281-node graphs exhausted the heap before first
     * paint. Startup may retain one household graph plus small UI metadata. */
    assert(fixture_nodes > 1000 && nodes_in(HomeHQ_Data()) < 600 && peak_json_nodes < 600 && overlays == 1);
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
    /* A fragmented heap can reject the mailbox view allocation. The dirty
     * update stays pending while the old graph/pixels remain usable. */
    lv_color_t mailbox_pixels[160 * 144]; memcpy(mailbox_pixels, pixels, sizeof(pixels));
    cJSON *pending_snapshot = cJSON_Parse(canonical_wire);
    cJSON_ReplaceItemInObject(pending_snapshot, "revision", cJSON_CreateNumber(2));
    fail_next_view_poll = true; transfer(pending_snapshot);
    assert(incoming_wire && get(HomeHQ_Data(), "revision")->valueint == 1 && !memcmp(mailbox_pixels, pixels, sizeof(pixels)));
    maintain(); assert(!incoming_wire && get(HomeHQ_Data(), "revision")->valueint == 2);
    /* Exercise the consumed driver edges, not console semantic replay. Held
     * Select is deliberately separate: GetState excludes it in factory code. */
    held = pressed = 1u << kButton_Right; maintain(); assert(!strcmp(HomeHQ_Page(), "calendar"));
    maintain(); assert(!strcmp(HomeHQ_Page(), "calendar")); held = 0;
    pressed = 1u << kButton_A; maintain(); assert(!strcmp(HomeHQ_Detail(), "event"));
    pressed = 1u << kButton_B; maintain(); assert(!HomeHQ_Detail()[0]);
    held = 1u << kButton_Select; maintain(); assert(!strcmp(HomeHQ_Detail(), "account"));
    pressed = 1u << kButton_A; maintain(); assert(!strcmp(HomeHQ_Detail(), "keyboard"));
    maintain(); assert(!strcmp(HomeHQ_Detail(), "keyboard")); held = 0; maintain(); input("b");
    cJSON *input_diagnostics = cJSON_CreateObject(); HomeHQ_InputDiagnostics(input_diagnostics);
    assert(get(input_diagnostics, "physical_right")->valueint == 1 && get(input_diagnostics, "physical_a")->valueint == 2);
    assert(get(input_diagnostics, "physical_select")->valueint == 1 && !truth(input_diagnostics, "snapshot_waiting"));
    cJSON_Delete(input_diagnostics); input("start");
    /* A malformed/allocation-failed decode must retain useful pixels, retry
     * and accept the next valid transfer without another full resident graph. */
    lv_color_t retained_pixels[160 * 144]; memcpy(retained_pixels, pixels, sizeof(pixels));
    cJSON *retry_snapshot = cJSON_Parse(homehq_demo_json); assert(retry_snapshot);
    fail_node_after = 20; transfer(retry_snapshot);
    assert(refresh_requests == 1 && nodes_in(HomeHQ_Data()) < 30 && !memcmp(retained_pixels, pixels, sizeof(pixels)));
    input("right"); assert(!strcmp(HomeHQ_Page(), "today"));
    input_diagnostics = cJSON_CreateObject(); HomeHQ_InputDiagnostics(input_diagnostics);
    assert(truth(input_diagnostics, "snapshot_waiting") && get(input_diagnostics, "blocked_inputs")->valueint >= 1);
    cJSON_Delete(input_diagnostics);
    transfer(cJSON_Parse(homehq_demo_json)); assert(nodes_in(HomeHQ_Data()) < 600);

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
    cJSON *changed = cJSON_Parse(canonical_wire);
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
    /* Retirement must follow widget deletion and precede a new request. A
     * matching pending delivery survives selection; fallback art remains honest
     * while a private path has not produced pixels. */
    const char *first_path = "11111111-1111-1111-1111-111111111111/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png";
    const char *second_path = "11111111-1111-1111-1111-111111111111/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png";
    changed = cJSON_Parse(canonical_wire);
    cJSON *photo_rows = (cJSON *)get(changed, "photos");
    int photo_first = HomeHQ_Focus(), photo_second = (photo_first + 1) % cJSON_GetArraySize(photo_rows);
    cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(photo_rows, photo_first), "path", cJSON_CreateString(first_path));
    cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetArrayItem(photo_rows, photo_second), "path", cJSON_CreateString(second_path));
    transfer(changed);
    assert(has_label(screen, "SAMPLE ART") && !strcmp(photo_requested_path, first_path));
    /* A previous frame's descriptor cannot start dwell for another path.
     * A native maximum-size photo now spans eighty fresh HTTPS connections;
     * waiting beyond twelve seconds must keep its request/selection alive. */
    snprintf(photo_loaded_path, sizeof(photo_loaded_path), "%s", second_path);
    vTaskDelay(20010); maintain();
    assert(HomeHQ_Focus() == photo_first && has_label(screen, "SAMPLE ART") &&
           !strcmp(photo_requested_path, first_path));
    snprintf(photo_loaded_path, sizeof(photo_loaded_path), "%s", first_path); photo_changed = true; maintain();
    assert(!has_label(screen, "SAMPLE ART") && has_image(screen));
    vTaskDelay(11999); maintain(); assert(HomeHQ_Focus() == photo_first);
    vTaskDelay(2); maintain(); assert(HomeHQ_Focus() == photo_second);
    input("up");
    snprintf(photo_loaded_path, sizeof(photo_loaded_path), "%s", first_path); photo_changed = true; maintain();
    unsigned resets_before = photo_resets, retires_before = photo_retires;
    snprintf(photo_pending_path, sizeof(photo_pending_path), "%s", second_path);
    input("down");
    assert(photo_retires == retires_before + 1 && photo_resets == resets_before);
    assert(!strcmp(photo_loaded_path, second_path) && !photo_pending_path[0] && !has_label(screen, "SAMPLE ART"));
    input("up"); assert(has_label(screen, "SAMPLE ART") && !photo_loaded_path[0]);
    snprintf(photo_loaded_path, sizeof(photo_loaded_path), "%s", first_path); photo_changed = true; maintain();
    /* An unavailable private frame must not trap autoplay forever. The bounded
     * fallback still gets a full visible dwell, and manual selection stays
     * immediate throughout the wait. */
    input("down"); assert(HomeHQ_Focus() == photo_second && has_label(screen, "SAMPLE ART"));
    vTaskDelay(300000); maintain(); assert(HomeHQ_Focus() == photo_second);
    vTaskDelay(11999); maintain(); assert(HomeHQ_Focus() == photo_second);
    vTaskDelay(2); maintain(); assert(HomeHQ_Focus() != photo_second);
    while (HomeHQ_Focus() > photo_first) input("up");
    while (HomeHQ_Focus() < photo_first) input("down");
    snprintf(photo_loaded_path, sizeof(photo_loaded_path), "%s", first_path); photo_changed = true; maintain();
    memcpy(retained_pixels, pixels, sizeof(pixels));
    /* Canceling an active TLS request cannot synchronously release its heap.
     * Keep valid photo widgets/model, perform no projected JSON allocations,
     * and preserve the physical Start/Right/A sequence until worker cleanup. */
    photo_worker_busy = true;
    unsigned hydrations_before = view_hydrations, polls_before = view_polls;
    const cJSON *retained_data = HomeHQ_Data();
    resets_before = photo_resets;
    input_diagnostics = cJSON_CreateObject(); HomeHQ_InputDiagnostics(input_diagnostics);
    unsigned blocked_before = get(input_diagnostics, "blocked_inputs")->valueint;
    cJSON_Delete(input_diagnostics);
    pressed = 1u << kButton_Start; maintain();
    assert(photo_worker_busy && photo_resets == resets_before + 1 && HomeHQ_Data() == retained_data);
    pressed = 1u << kButton_Right; maintain();
    pressed = 1u << kButton_A; maintain();
    assert(view_hydrations == hydrations_before && view_polls == polls_before &&
           has_image(screen) && !memcmp(retained_pixels, pixels, sizeof(pixels)));
    photo_worker_busy = false; maintain();
    assert(!strcmp(HomeHQ_Page(), "calendar") && !strcmp(HomeHQ_Detail(), "event") && !has_image(screen));
    input_diagnostics = cJSON_CreateObject(); HomeHQ_InputDiagnostics(input_diagnostics);
    assert(get(input_diagnostics, "blocked_inputs")->valueint == (int)blocked_before &&
           !truth(input_diagnostics, "snapshot_waiting"));
    cJSON_Delete(input_diagnostics);
    seek("photos");
    snprintf(photo_loaded_path, sizeof(photo_loaded_path), "%s", first_path); photo_changed = true; maintain();
    memcpy(retained_pixels, pixels, sizeof(pixels));
    /* Start cancels the request before hydration, but a failed destination
     * allocation retains valid old widgets/pixels until its successful retry. */
    resets_before = photo_resets; fail_next_view_hydration = true;
    input("start");
    assert(photo_resets == resets_before + 1 && !photo_requested_path[0]);
    assert(!strcmp(photo_loaded_path, first_path) && has_image(screen) && !memcmp(retained_pixels, pixels, sizeof(pixels)));
    input_diagnostics = cJSON_CreateObject(); HomeHQ_InputDiagnostics(input_diagnostics);
    assert(truth(input_diagnostics, "snapshot_waiting")); cJSON_Delete(input_diagnostics);
    vTaskDelay(1001); maintain();
    assert(!strcmp(HomeHQ_Page(), "today") && !photo_loaded_path[0] && !has_image(screen));
    seek("agents"); input("a"); assert(!strcmp(HomeHQ_Detail(), "agent"));
    assert(has_label(screen, "Weekly / all models") && !has_label(screen, "Weekly \xC2\xB7"));
    preview(argv[1], "agent-detail");

    /* DST repeats 1:00 AM locally. Next-event selection/countdown must still
     * see the event thirty UTC minutes ahead, at the later endpoint offset. */
    changed = cJSON_Parse(canonical_wire);
    cJSON_ReplaceItemInObject(changed, "server_time", cJSON_CreateNumber(1793512200));
    cJSON_ReplaceItemInObject((cJSON *)get(changed, "home"), "utc_offset_minutes", cJSON_CreateNumber(-240));
    cJSON_ReplaceItemInObject(changed, "events", cJSON_Parse("[{\"id\":\"dst\",\"start\":1793514000,\"end\":1793514600,\"start_offset_minutes\":-300,\"end_offset_minutes\":-300,\"title\":\"DST event\",\"people\":[\"alex\"],\"all_day\":false}]"));
    transfer(changed); seek("today"); assert(has_label(screen, "DST event") && has_label(screen, "30 minutes"));
    changed = cJSON_Parse(canonical_wire);
    cJSON_ReplaceItemInObject(cJSON_GetArrayItem((cJSON *)get(changed, "events"), 0), "title", cJSON_CreateString("Keep 20\xC2\xB0"));
    transfer(changed); assert(has_label(screen, "20\xC2\xB0"));

    /* A verified viewer owns both preferred chores and Anyone credit. */
    changed = cJSON_Parse(homehq_demo_json);
    cJSON_AddItemToObject(changed, "viewer", cJSON_Parse("{\"user_id\":\"member-one\",\"person_id\":\"maya\"}"));
    transfer(changed); seek("chores"); assert(HomeHQ_Focus() == 2);
    repeated("down", 2); input("a"); input("a"); assert(!strcmp(str(last_command, "done_by"), "maya"));
    seek("shopping"); repeated("down", 3);
    memcpy(retained_pixels, pixels, sizeof(pixels));
    changed = cJSON_Parse(canonical_wire); fail_node_after = 20; transfer(changed);
    assert(!memcmp(retained_pixels, pixels, sizeof(pixels)));
    transfer(cJSON_Parse(canonical_wire));
    assert(!strcmp(HomeHQ_Page(), "shopping") && HomeHQ_Focus() == 3);
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
    printf("PASS native navigation, desired-state writes, confirmation, identity, DST, slideshow, printable-ASCII masked sign-in and single-graph wire ownership (%u frames, fixture %u nodes)\n", frames, fixture_nodes);
    return 0;
}
