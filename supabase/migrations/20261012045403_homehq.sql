SET local check_function_bodies = off;

CREATE SCHEMA "homehq_private";

CREATE TABLE "public"."homehq_cards" (
  "section"    text                     NOT NULL,
  "data"       jsonb                    NOT NULL,
  "updated_at" timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "homehq_cards_check" CHECK (
CASE
    WHEN (section = 'agents'::text) THEN
    CASE
        WHEN (jsonb_typeof(data) = 'array'::text) THEN (jsonb_array_length(data) <= 8)
        ELSE false
    END
    ELSE (jsonb_typeof(data) = 'object'::text)
END),
  CONSTRAINT "homehq_cards_data_check" CHECK ((octet_length((data)::text) <= 8192)),
  CONSTRAINT "homehq_cards_section_check" CHECK ((section = ANY (ARRAY['weather'::text, 'home_status'::text, 'agents'::text]))),
  "owner_id"   uuid                     NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_cards_pkey" PRIMARY KEY (owner_id, section)
);

ALTER TABLE "public"."homehq_cards"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_cards" FROM "anon";

CREATE TABLE "public"."homehq_checklist" (
  "kind"       text    NOT NULL,
  "id"         text    NOT NULL,
  "title"      text    NOT NULL,
  "person_id"  text,
  "routine"    text,
  "stars"      integer NOT NULL DEFAULT 0,
  "category"   text    NOT NULL DEFAULT ''::text,
  "store"      text    NOT NULL DEFAULT ''::text,
  "quantity"   integer NOT NULL DEFAULT 1,
  "note"       text    NOT NULL DEFAULT ''::text,
  "done"       boolean NOT NULL DEFAULT false,
  "done_by"    text,
  "version"    bigint  NOT NULL DEFAULT 1,
  "sort_order" integer NOT NULL DEFAULT 0,
  CONSTRAINT "homehq_checklist_category_check" CHECK ((char_length(category) <= 40)),
  CONSTRAINT "homehq_checklist_check1" CHECK (((kind <> 'chore'::text) OR ((NOT done) AND (done_by IS NULL)) OR (done AND (done_by IS
    NOT NULL) AND ((person_id IS NULL) OR (done_by = person_id))))),
  CONSTRAINT "homehq_checklist_check" CHECK ((((kind = 'chore'::text) AND (routine IS
    NOT NULL)) OR ((kind = 'shopping'::text) AND (person_id IS NULL) AND (routine IS NULL) AND (stars = 0) AND (done_by IS NULL)))),
  CONSTRAINT "homehq_checklist_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,32}$'::text)),
  CONSTRAINT "homehq_checklist_kind_check" CHECK ((kind = ANY (ARRAY['chore'::text, 'shopping'::text]))),
  CONSTRAINT "homehq_checklist_note_check" CHECK ((char_length(note) <= 160)),
  CONSTRAINT "homehq_checklist_quantity_check" CHECK (((quantity >= 1) AND (quantity <= 999))),
  CONSTRAINT "homehq_checklist_routine_check" CHECK ((routine = ANY (ARRAY['morning'::text, 'after'::text, 'evening'::text]))),
  CONSTRAINT "homehq_checklist_stars_check" CHECK (((stars >= 0) AND (stars <= 99))),
  CONSTRAINT "homehq_checklist_store_check" CHECK ((char_length(store) <= 40)),
  CONSTRAINT "homehq_checklist_title_check" CHECK (((char_length(title) >= 1) AND (char_length(title) <= 100))),
  CONSTRAINT "homehq_checklist_version_check" CHECK ((version > 0)),
  "owner_id"   uuid    NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_checklist_pkey" PRIMARY KEY (owner_id, kind, id)
);

ALTER TABLE "public"."homehq_checklist"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_checklist" FROM "anon";

CREATE TABLE "public"."homehq_devices" (
  "id"           text    NOT NULL,
  "name"         text    NOT NULL,
  "room"         text    NOT NULL,
  "type"         text    NOT NULL,
  "on_state"     boolean,
  "level"        integer,
  "locked"       boolean,
  "garage_state" text,
  "version"      bigint  NOT NULL DEFAULT 1,
  "sort_order"   integer NOT NULL DEFAULT 0,
  CONSTRAINT "homehq_devices_check" CHECK ((((type = 'light'::text) AND (on_state IS NOT NULL) AND (level IS
    NOT NULL) AND (locked IS NULL) AND (garage_state IS NULL)) OR ((type = 'lock'::text) AND (locked IS
    NOT NULL) AND (on_state IS NULL) AND (level IS NULL) AND (garage_state IS NULL)) OR ((type = 'garage'::text) AND (garage_state IS
    NOT NULL) AND (on_state IS NULL) AND (level IS NULL) AND (locked IS NULL)))),
  CONSTRAINT "homehq_devices_garage_state_check" CHECK ((garage_state = ANY (ARRAY['open'::text, 'closed'::text]))),
  CONSTRAINT "homehq_devices_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,32}$'::text)),
  CONSTRAINT "homehq_devices_level_check" CHECK (((level >= 0) AND (level <= 100))),
  CONSTRAINT "homehq_devices_name_check" CHECK (((char_length(name) >= 1) AND (char_length(name) <= 40))),
  CONSTRAINT "homehq_devices_room_check" CHECK (((char_length(room) >= 1) AND (char_length(room) <= 40))),
  CONSTRAINT "homehq_devices_type_check" CHECK ((type = ANY (ARRAY['light'::text, 'lock'::text, 'garage'::text]))),
  CONSTRAINT "homehq_devices_version_check" CHECK ((version > 0)),
  "owner_id"     uuid    NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_devices_pkey" PRIMARY KEY (owner_id, id)
);

ALTER TABLE "public"."homehq_devices"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_devices" FROM "anon";

CREATE TABLE "public"."homehq_event_people" (
  "event_id"  text NOT NULL,
  "person_id" text NOT NULL,
  "owner_id"  uuid NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_event_people_pkey" PRIMARY KEY (owner_id, event_id, person_id)
);

ALTER TABLE "public"."homehq_event_people"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_event_people" FROM "anon";

CREATE TABLE "public"."homehq_events" (
  "id"        text                     NOT NULL,
  "starts_at" timestamp with time zone NOT NULL,
  "ends_at"   timestamp with time zone NOT NULL,
  "title"     text                     NOT NULL,
  "travel"    integer                  NOT NULL DEFAULT 0,
  "loc"       text                     NOT NULL DEFAULT ''::text,
  "notes"     text                     NOT NULL DEFAULT ''::text,
  "all_day"   boolean                  NOT NULL DEFAULT false,
  CONSTRAINT "homehq_events_check" CHECK ((ends_at >= starts_at)),
  CONSTRAINT "homehq_events_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,32}$'::text)),
  CONSTRAINT "homehq_events_loc_check" CHECK ((char_length(loc) <= 120)),
  CONSTRAINT "homehq_events_notes_check" CHECK ((char_length(notes) <= 240)),
  CONSTRAINT "homehq_events_title_check" CHECK (((char_length(title) >= 1) AND (char_length(title) <= 100))),
  CONSTRAINT "homehq_events_travel_check" CHECK (((travel >= 0) AND (travel <= 1440))),
  "owner_id"  uuid                     NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_events_pkey" PRIMARY KEY (owner_id, id)
);

ALTER TABLE "public"."homehq_events"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_events" FROM "anon";

CREATE TABLE "public"."homehq_homes" (
  "title"      text                     NOT NULL DEFAULT 'Home HQ'::text,
  "timezone"   text                     NOT NULL DEFAULT 'America/Toronto'::text,
  "demo"       boolean                  NOT NULL DEFAULT true,
  "revision"   bigint                   NOT NULL DEFAULT 1,
  "updated_at" timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT "homehq_homes_revision_check" CHECK ((revision > 0)),
  CONSTRAINT "homehq_homes_timezone_check" CHECK (((char_length(timezone) >= 1) AND (char_length(timezone) <= 80))),
  CONSTRAINT "homehq_homes_title_check" CHECK (((char_length(title) >= 1) AND (char_length(title) <= 60))),
  "owner_id"   uuid                     NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_homes_pkey" PRIMARY KEY (owner_id)
);

ALTER TABLE "public"."homehq_homes"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_homes" FROM "anon";

CREATE TABLE "public"."homehq_people" (
  "id"         text    NOT NULL,
  "name"       text    NOT NULL,
  "color"      text    NOT NULL,
  "home"       boolean NOT NULL DEFAULT true,
  "status"     text    NOT NULL DEFAULT 'Home'::text,
  "eta"        integer,
  "sort_order" integer NOT NULL DEFAULT 0,
  CONSTRAINT "homehq_people_color_check" CHECK ((color ~ '^#[0-9A-Fa-f]{6}$'::text)),
  CONSTRAINT "homehq_people_eta_check" CHECK (((eta >= 0) AND (eta <= 1440))),
  CONSTRAINT "homehq_people_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,32}$'::text)),
  CONSTRAINT "homehq_people_name_check" CHECK (((char_length(name) >= 1) AND (char_length(name) <= 40))),
  CONSTRAINT "homehq_people_status_check" CHECK ((char_length(status) <= 80)),
  "owner_id"   uuid    NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_people_pkey" PRIMARY KEY (owner_id, id)
);

ALTER TABLE "public"."homehq_people"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_people" FROM "anon";

CREATE TABLE "public"."homehq_photos" (
  "id"         text    NOT NULL,
  "path"       text,
  "asset"      text    NOT NULL DEFAULT 'assets/photo-coast.png'::text,
  "caption"    text    NOT NULL DEFAULT ''::text,
  "place"      text    NOT NULL DEFAULT ''::text,
  "sort_order" integer NOT NULL DEFAULT 0,
  CONSTRAINT "homehq_photos_asset_check" CHECK ((asset ~ '^assets/[a-z0-9_-]+\.png$'::text)),
  CONSTRAINT "homehq_photos_caption_check" CHECK ((char_length(caption) <= 60)),
  CONSTRAINT "homehq_photos_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,32}$'::text)),
  CONSTRAINT "homehq_photos_place_check" CHECK ((char_length(place) <= 80)),
  "owner_id"   uuid    NOT NULL DEFAULT auth.uid(),
  CONSTRAINT "homehq_photos_check" CHECK (((path IS NULL) OR (path ~ (('^'::text || (owner_id)::text) || '/[0-9a-f]{64}\.png$'::text)))),
  CONSTRAINT "homehq_photos_pkey" PRIMARY KEY (owner_id, id)
);

ALTER TABLE "public"."homehq_photos"
  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE "public"."homehq_photos" FROM "anon";

CREATE OR REPLACE FUNCTION homehq_private.broadcast_change()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  SECURITY DEFINER
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid;
  v_revision bigint;
  v_section text := tg_argv[0];
begin
  if tg_op = 'DELETE' then v_owner := old.owner_id; else v_owner := new.owner_id; end if;
  if tg_table_name = 'homehq_checklist' then
    if tg_op = 'DELETE' then
      v_section := case old.kind when 'chore' then 'chores' else 'shopping' end;
    else
      v_section := case new.kind when 'chore' then 'chores' else 'shopping' end;
    end if;
  elsif tg_table_name = 'homehq_cards' then
    if tg_op = 'DELETE' then v_section := old.section; else v_section := new.section; end if;
  end if;
  if tg_table_name = 'homehq_homes' then
    if tg_op = 'DELETE' then v_revision := old.revision; else v_revision := new.revision; end if;
  else
    update public.homehq_homes set revision = revision + 1, updated_at = now()
      where owner_id = v_owner returning revision into v_revision;
    -- A cascading home deletion has already removed the revision row.
    if v_revision is null then return null; end if;
  end if;
  -- Definer is limited to this trigger: clients cannot call it or send their own
  -- Broadcasts. It updates the server-owned revision and inserts into Supabase's
  -- managed message store; recipient authorization remains its RLS policy.
  perform realtime.send(
    jsonb_build_object('section', v_section, 'revision', v_revision),
    'changed', 'homehq:' || v_owner::text, true
  );
  return null;
end;
$function$;

CREATE OR REPLACE FUNCTION homehq_private.bump_version()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  SET search_path TO ''
  AS $function$
begin
  -- The server owns versions even when the companion edits a row directly.
  -- Replays never reach this trigger: the RPC returns matching state first.
  new.version := old.version + 1;
  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION homehq_private.device_json (
  p_device public.homehq_devices
)
  RETURNS jsonb
  LANGUAGE sql
  IMMUTABLE
  SET search_path TO ''
  AS $function$
  select jsonb_strip_nulls(jsonb_build_object(
    'id', p_device.id, 'name', p_device.name, 'room', p_device.room, 'type', p_device.type,
    'on', p_device.on_state, 'level', p_device.level, 'locked', p_device.locked,
    'state', p_device.garage_state, 'version', p_device.version, 'sample', true
  ));
$function$;

CREATE OR REPLACE FUNCTION homehq_private.item_json (
  p_item public.homehq_checklist
)
  RETURNS jsonb
  LANGUAGE sql
  IMMUTABLE
  SET search_path TO ''
  AS $function$
  select case when p_item.kind = 'chore' then jsonb_build_object(
    'id', p_item.id, 'who', coalesce(p_item.person_id, 'any'), 'routine', p_item.routine,
    'title', p_item.title, 'stars', p_item.stars, 'done', p_item.done,
    'done_by', p_item.done_by, 'version', p_item.version
  ) else jsonb_build_object(
    'id', p_item.id, 'name', p_item.title, 'category', p_item.category,
    'store', p_item.store, 'quantity', p_item.quantity, 'note', p_item.note,
    'done', p_item.done, 'version', p_item.version
  ) end;
$function$;

CREATE OR REPLACE FUNCTION homehq_private.validate_home()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  SET search_path TO ''
  AS $function$
begin
  if not exists (select 1 from pg_catalog.pg_timezone_names where name = new.timezone) then
    raise exception using errcode = '22023', message = 'Unknown home timezone';
  end if;
  if tg_op = 'UPDATE' then
    new.revision := old.revision + 1;
    new.updated_at := now();
  end if;
  return new;
end;
$function$;

CREATE OR REPLACE FUNCTION public.homehq_seed_demo (
  p_replace boolean DEFAULT false
)
  RETURNS jsonb
  LANGUAGE plpgsql
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid := auth.uid();
  v_home public.homehq_homes;
  v_fixture jsonb := $fixture${"schema_version":1,"revision":1,"server_time":1791746280,"home":{"title":"Home HQ","timezone":"America/Toronto","utc_offset_minutes":-240,"demo":true},"people":[{"id":"alex","name":"Wes","color":"#2D5BFF","home":false,"status":"Driving home","eta":12},{"id":"jordan","name":"Claudia","color":"#E4007C","home":false,"status":"At the office","eta":null},{"id":"maya","name":"Buzzsaw","color":"#00A36C","home":true,"status":"Home","eta":null},{"id":"otto","name":"Skidmark","color":"#FFB000","home":true,"status":"Home","eta":null}],"events":[{"id":"e1","start":1791691200,"end":1791777600,"title":"Pajama Day at school","people":["otto"],"travel":0,"loc":"","notes":"","all_day":true},{"id":"e2","start":1791691200,"end":1791777600,"title":"Garbage + recycling night","people":["alex","jordan","maya","otto"],"travel":0,"loc":"","notes":"","all_day":true},{"id":"e3","start":1791716400,"end":1791719100,"title":"Gym","people":["jordan"],"travel":0,"loc":"Iron Works","notes":"","all_day":false},{"id":"e4","start":1791720900,"end":1791722400,"title":"School drop-off","people":["alex"],"travel":10,"loc":"Parkdale Elementary","notes":"","all_day":false},{"id":"e5","start":1791725400,"end":1791729000,"title":"Design review","people":["jordan"],"travel":0,"loc":"Office · Room 4B","notes":"","all_day":false},{"id":"e6","start":1791734400,"end":1791737100,"title":"Dentist","people":["maya","jordan"],"travel":15,"loc":"Bright Smiles Dental","notes":"","all_day":false},{"id":"e7","start":1791738000,"end":1791741600,"title":"Lunch with Sam","people":["alex"],"travel":0,"loc":"Café Rustica","notes":"","all_day":false},{"id":"e8","start":1791747900,"end":1791750600,"title":"Piano lesson","people":["otto"],"travel":12,"loc":"Ms. Park's Studio","notes":"Bring the blue theory book.","all_day":false},{"id":"e9","start":1791749100,"end":1791750600,"title":"Drive Buzzsaw to soccer","people":["jordan"],"travel":0,"loc":"","notes":"","all_day":false},{"id":"e10","start":1791750300,"end":1791751800,"title":"Pick up Skidmark","people":["jordan"],"travel":0,"loc":"Ms. Park's Studio","notes":"","all_day":false},{"id":"e11","start":1791750600,"end":1791756000,"title":"Soccer practice","people":["maya"],"travel":20,"loc":"Lakeshore Fields","notes":"Shin guards + water bottle. Rain likely — pack a jacket.","all_day":false},{"id":"e12","start":1791752400,"end":1791754200,"title":"Parent–teacher call","people":["alex","jordan"],"travel":0,"loc":"Zoom","notes":"","all_day":false},{"id":"e13","start":1791757800,"end":1791761400,"title":"Dinner at Nonna's","people":["alex","jordan","maya","otto"],"travel":20,"loc":"Nonna's","notes":"Bring the lemon cake.","all_day":false},{"id":"e14","start":1791763200,"end":1791765000,"title":"Bath + books","people":["otto"],"travel":0,"loc":"","notes":"","all_day":false},{"id":"e15","start":1791777600,"end":1792036800,"title":"Wes in Montréal","people":["alex"],"travel":0,"loc":"Hotel William Gray","notes":"","all_day":true},{"id":"e16","start":1791802800,"end":1791805500,"title":"Gym","people":["jordan"],"travel":0,"loc":"Iron Works","notes":"","all_day":false},{"id":"e17","start":1791807300,"end":1791808800,"title":"School drop-off","people":["jordan"],"travel":10,"loc":"","notes":"","all_day":false},{"id":"e18","start":1791815400,"end":1791818100,"title":"Vet — Biscuit","people":["jordan"],"travel":10,"loc":"Riverdale Animal Clinic","notes":"","all_day":false},{"id":"e19","start":1791833400,"end":1791837000,"title":"Art club","people":["maya"],"travel":0,"loc":"School","notes":"","all_day":false},{"id":"e20","start":1791835200,"end":1791842400,"title":"Playdate with Leo","people":["otto"],"travel":8,"loc":"Leo's house","notes":"","all_day":false},{"id":"e21","start":1791846000,"end":1791853200,"title":"Book club","people":["jordan"],"travel":10,"loc":"Priya's","notes":"","all_day":false},{"id":"e22","start":1791896400,"end":1791914400,"title":"Science Centre trip","people":["otto"],"travel":0,"loc":"Ontario Science Centre","notes":"","all_day":false},{"id":"e23","start":1791910800,"end":1791913500,"title":"Haircuts","people":["maya","otto"],"travel":10,"loc":"Snip Snip Kids","notes":"","all_day":false},{"id":"e24","start":1791923400,"end":1791928800,"title":"Soccer practice","people":["maya"],"travel":20,"loc":"Lakeshore Fields","notes":"","all_day":false},{"id":"e25","start":1791928800,"end":1791934200,"title":"Pizza night","people":["alex","jordan","maya","otto"],"travel":0,"loc":"","notes":"","all_day":false},{"id":"e26","start":1791986400,"end":1791989100,"title":"Swim lessons","people":["otto"],"travel":12,"loc":"Wellesley Pool","notes":"","all_day":false},{"id":"e27","start":1791990000,"end":1791993600,"title":"Grocery run","people":["jordan"],"travel":0,"loc":"","notes":"","all_day":false},{"id":"e28","start":1791997200,"end":1792006200,"title":"Zoe's birthday party","people":["maya"],"travel":15,"loc":"Pottery Place","notes":"","all_day":false},{"id":"e29","start":1792018800,"end":1792026000,"title":"Movie night","people":["alex","jordan","maya","otto"],"travel":0,"loc":"","notes":"","all_day":false},{"id":"e30","start":1792074600,"end":1792080000,"title":"Sunday brunch","people":["alex","jordan","maya","otto"],"travel":15,"loc":"Lady Marmalade","notes":"","all_day":false},{"id":"e31","start":1792098300,"end":1792102800,"title":"Flight home · AC 418","people":["alex"],"travel":0,"loc":"YUL → YYZ","notes":"","all_day":false},{"id":"e32","start":1792148400,"end":1792151100,"title":"Gym","people":["jordan"],"travel":0,"loc":"","notes":"","all_day":false},{"id":"e33","start":1792179900,"end":1792182600,"title":"Piano lesson","people":["otto"],"travel":12,"loc":"","notes":"","all_day":false},{"id":"e34","start":1792182600,"end":1792188000,"title":"Soccer practice","people":["maya"],"travel":20,"loc":"","notes":"","all_day":false},{"id":"e35","start":1792191600,"end":1792195200,"title":"Yoga","people":["jordan"],"travel":0,"loc":"","notes":"","all_day":false},{"id":"e36","start":1792209600,"end":1792382400,"title":"Grandma visits","people":["alex","jordan","maya","otto"],"travel":0,"loc":"","notes":"","all_day":true},{"id":"e37","start":1792242000,"end":1792244700,"title":"Dentist","people":["otto"],"travel":15,"loc":"Bright Smiles Dental","notes":"","all_day":false},{"id":"e38","start":1792269000,"end":1792274400,"title":"Soccer practice","people":["maya"],"travel":20,"loc":"","notes":"","all_day":false}],"chores":[{"id":"c1","who":"maya","routine":"morning","title":"Make bed","stars":1,"done":true,"done_by":"maya","version":1},{"id":"c2","who":"maya","routine":"morning","title":"Brush teeth","stars":1,"done":true,"done_by":"maya","version":1},{"id":"c3","who":"maya","routine":"morning","title":"Pack backpack","stars":1,"done":true,"done_by":"maya","version":1},{"id":"c4","who":"otto","routine":"morning","title":"Make bed","stars":1,"done":true,"done_by":"otto","version":1},{"id":"c5","who":"otto","routine":"morning","title":"Brush teeth","stars":1,"done":true,"done_by":"otto","version":1},{"id":"c6","who":"otto","routine":"morning","title":"Get dressed","stars":1,"done":false,"done_by":null,"version":1},{"id":"c7","who":"alex","routine":"morning","title":"School drop-off","stars":0,"done":true,"done_by":"alex","version":1},{"id":"c8","who":"jordan","routine":"morning","title":"Pack lunches","stars":0,"done":true,"done_by":"jordan","version":1},{"id":"c9","who":"any","routine":"morning","title":"Feed Biscuit","stars":1,"done":true,"done_by":"alex","version":1},{"id":"c10","who":"maya","routine":"after","title":"Unpack lunchbox","stars":1,"done":true,"done_by":"maya","version":1},{"id":"c11","who":"maya","routine":"after","title":"Homework","stars":2,"done":false,"done_by":null,"version":1},{"id":"c12","who":"maya","routine":"after","title":"Pack soccer bag","stars":1,"done":false,"done_by":null,"version":1},{"id":"c13","who":"otto","routine":"after","title":"Unpack lunchbox","stars":1,"done":true,"done_by":"otto","version":1},{"id":"c14","who":"otto","routine":"after","title":"Read for 20 min","stars":2,"done":false,"done_by":null,"version":1},{"id":"c15","who":"otto","routine":"after","title":"Practice piano","stars":2,"done":false,"done_by":null,"version":1},{"id":"c16","who":"otto","routine":"after","title":"Tidy the Lego","stars":1,"done":false,"done_by":null,"version":1},{"id":"c17","who":"alex","routine":"after","title":"Take out recycling","stars":0,"done":false,"done_by":null,"version":1},{"id":"c18","who":"alex","routine":"after","title":"Call the plumber","stars":0,"done":true,"done_by":"alex","version":1},{"id":"c19","who":"jordan","routine":"after","title":"Fold laundry","stars":0,"done":false,"done_by":null,"version":1},{"id":"c20","who":"jordan","routine":"after","title":"Order Zoe’s gift","stars":0,"done":true,"done_by":"jordan","version":1},{"id":"c21","who":"any","routine":"after","title":"Water the plants","stars":1,"done":false,"done_by":null,"version":1},{"id":"c22","who":"any","routine":"after","title":"Empty dishwasher","stars":2,"done":false,"done_by":null,"version":1},{"id":"c23","who":"any","routine":"after","title":"Walk Biscuit","stars":2,"done":true,"done_by":"alex","version":1},{"id":"c24","who":"maya","routine":"evening","title":"Set the table","stars":1,"done":false,"done_by":null,"version":1},{"id":"c25","who":"maya","routine":"evening","title":"Lay out clothes","stars":1,"done":false,"done_by":null,"version":1},{"id":"c26","who":"maya","routine":"evening","title":"Shower","stars":1,"done":false,"done_by":null,"version":1},{"id":"c27","who":"otto","routine":"evening","title":"Clear plates","stars":1,"done":false,"done_by":null,"version":1},{"id":"c28","who":"otto","routine":"evening","title":"Bath","stars":1,"done":false,"done_by":null,"version":1},{"id":"c29","who":"otto","routine":"evening","title":"Lay out clothes","stars":1,"done":false,"done_by":null,"version":1},{"id":"c30","who":"alex","routine":"evening","title":"Lock up","stars":0,"done":false,"done_by":null,"version":1},{"id":"c31","who":"jordan","routine":"evening","title":"Run dishwasher","stars":0,"done":false,"done_by":null,"version":1},{"id":"c32","who":"any","routine":"evening","title":"Wipe counters","stars":1,"done":false,"done_by":null,"version":1},{"id":"c33","who":"any","routine":"evening","title":"Garbage to curb","stars":2,"done":false,"done_by":null,"version":1}],"shopping":[{"id":"g1","name":"Bananas","category":"Produce","store":"FreshCo","quantity":1,"note":"Bunch, not too ripe","done":false,"version":1},{"id":"g2","name":"Baby spinach","category":"Produce","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g3","name":"Avocados","category":"Produce","store":"FreshCo","quantity":3,"note":"","done":false,"version":1},{"id":"g4","name":"Honeycrisp apples","category":"Produce","store":"FreshCo","quantity":6,"note":"","done":false,"version":1},{"id":"g5","name":"Sourdough loaf","category":"Bakery","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g6","name":"Bagels","category":"Bakery","store":"Costco","quantity":2,"note":"Everything","done":false,"version":1},{"id":"g7","name":"Chicken thighs","category":"Meat & Fish","store":"FreshCo","quantity":1,"note":"Boneless","done":false,"version":1},{"id":"g8","name":"Salmon fillets","category":"Meat & Fish","store":"FreshCo","quantity":2,"note":"","done":false,"version":1},{"id":"g9","name":"Milk 2%","category":"Dairy & Eggs","store":"Costco","quantity":2,"note":"","done":false,"version":1},{"id":"g10","name":"Eggs","category":"Dairy & Eggs","store":"Costco","quantity":1,"note":"2 dozen","done":false,"version":1},{"id":"g11","name":"Greek yogurt","category":"Dairy & Eggs","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g12","name":"Aged cheddar","category":"Dairy & Eggs","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g13","name":"Rigatoni","category":"Pantry","store":"FreshCo","quantity":2,"note":"","done":false,"version":1},{"id":"g14","name":"Olive oil","category":"Pantry","store":"Costco","quantity":1,"note":"","done":false,"version":1},{"id":"g15","name":"Coffee beans","category":"Pantry","store":"FreshCo","quantity":1,"note":"Dark roast","done":false,"version":1},{"id":"g16","name":"Frozen peas","category":"Frozen","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g17","name":"Waffles","category":"Frozen","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g18","name":"Goldfish crackers","category":"Snacks","store":"Costco","quantity":1,"note":"","done":false,"version":1},{"id":"g19","name":"Granola bars","category":"Snacks","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g20","name":"Paper towels","category":"Household","store":"Costco","quantity":1,"note":"","done":false,"version":1},{"id":"g21","name":"Dish soap","category":"Household","store":"FreshCo","quantity":1,"note":"","done":false,"version":1},{"id":"g22","name":"Lemons","category":"Produce","store":"FreshCo","quantity":2,"note":"","done":true,"version":1},{"id":"g23","name":"Butter","category":"Dairy & Eggs","store":"FreshCo","quantity":1,"note":"","done":true,"version":1},{"id":"g24","name":"Tortillas","category":"Bakery","store":"FreshCo","quantity":1,"note":"","done":true,"version":1}],"photos":[{"id":"p1","path":null,"asset":"assets/photo-coast.png","caption":"On this day","place":"Tofino, BC"},{"id":"p2","path":null,"asset":"assets/photo-coast.png","caption":"2023-08-12","place":"Lake of Bays"},{"id":"p3","path":null,"asset":"assets/photo-coast.png","caption":"2024-05-19","place":"Humber Bay Park"},{"id":"p4","path":null,"asset":"assets/photo-coast.png","caption":"2024-05-19","place":"Humber Bay Park"},{"id":"p5","path":null,"asset":"assets/photo-coast.png","caption":"2022-10-09","place":"High Park"},{"id":"p6","path":null,"asset":"assets/photo-coast.png","caption":"2025-10-12","place":"Home"},{"id":"p7","path":null,"asset":"assets/photo-coast.png","caption":"2025-10-12","place":"Home"},{"id":"p8","path":null,"asset":"assets/photo-coast.png","caption":"On this day","place":"Banff, AB"},{"id":"p9","path":null,"asset":"assets/photo-coast.png","caption":"2024-01-21","place":"Riverdale Hill"},{"id":"p10","path":null,"asset":"assets/photo-coast.png","caption":"2023-07-02","place":"Sandbanks"},{"id":"p11","path":null,"asset":"assets/photo-coast.png","caption":"2022-12-18","place":"Nathan Phillips Sq."},{"id":"p12","path":null,"asset":"assets/photo-coast.png","caption":"2025-06-08","place":"Backyard"},{"id":"p13","path":null,"asset":"assets/photo-coast.png","caption":"2025-06-08","place":"Backyard"},{"id":"p14","path":null,"asset":"assets/photo-coast.png","caption":"2024-08-04","place":"Cabot Trail, NS"},{"id":"p15","path":null,"asset":"assets/photo-coast.png","caption":"2024-08-06","place":"Cape Breton"},{"id":"p16","path":null,"asset":"assets/photo-coast.png","caption":"2020-09-26","place":"Algonquin"},{"id":"p17","path":null,"asset":"assets/photo-coast.png","caption":"2026-03-14","place":"Home"},{"id":"p18","path":null,"asset":"assets/photo-coast.png","caption":"2026-03-14","place":"Sugar Shack"},{"id":"p19","path":null,"asset":"assets/photo-coast.png","caption":"2025-07-19","place":"Toronto Harbour"},{"id":"p20","path":null,"asset":"assets/photo-coast.png","caption":"2025-10-25","place":"Chudleigh's"}],"weather":{"temp":15,"label":"Overcast","high":17,"low":8,"summary":"Rain from 4 PM","sample":true},"home_status":{"temperature":20.5,"lights_on":3,"locked":true,"sample":true},"agents":[{"id":"claude","name":"Claude","color":"#D97757","sample":true,"meters":[{"label":"Session","used":62,"reset_minutes":134},{"label":"Weekly · all models","used":41,"reset_minutes":4680}],"week":[2.2,3.8,2.9,4.4,1.6,0.8,3.1]},{"id":"codex","name":"Codex","color":"#10A37F","sample":true,"meters":[{"label":"Session","used":88,"reset_minutes":38},{"label":"Weekly","used":57,"reset_minutes":7320}],"week":[3.1,2.4,5.2,4,2.2,1.1,4.6]},{"id":"cursor","name":"Cursor","color":"#111111","sample":true,"meters":[{"label":"Included usage","used":76,"reset_minutes":17280},{"label":"On-demand","used":16,"reset_minutes":17280}],"week":[1.2,1.9,0.7,2.3,1.5,0.4,1.8]},{"id":"gemini","name":"Gemini","color":"#3F6FE4","sample":true,"meters":[{"label":"Requests · daily","used":16,"reset_minutes":522},{"label":"Pro model · daily","used":52,"reset_minutes":522}],"week":[0.4,1.1,0.6,0.2,0.9,1.3,0.9]},{"id":"copilot","name":"Copilot","color":"#8957E5","sample":true,"meters":[{"label":"Premium requests","used":75,"reset_minutes":17280},{"label":"Coding agent","used":38,"reset_minutes":17280}],"week":[0.9,1.4,1.1,0.8,1.6,0.3,1.2]}],"devices":[{"id":"kitchen-light","name":"Kitchen lights","room":"Kitchen","type":"light","on":true,"level":80,"version":1,"sample":true},{"id":"living-light","name":"Floor lamp","room":"Living Room","type":"light","on":true,"level":45,"version":1,"sample":true},{"id":"porch-light","name":"Porch light","room":"Entry","type":"light","on":true,"level":100,"version":1,"sample":true},{"id":"garage-door","name":"Garage door","room":"Garage","type":"garage","state":"closed","version":1,"sample":true},{"id":"front-door","name":"Front door","room":"Entry","type":"lock","locked":true,"version":1,"sample":true}]}$fixture$::jsonb;
  v_row jsonb;
  v_i integer;
  v_today date;
  v_person text;
begin
  if v_owner is null then raise exception using errcode = '42501', message = 'Sign in to Home HQ'; end if;
  if p_replace is null then raise exception using errcode = '22023', message = 'Specify whether to replace demo data'; end if;
  insert into public.homehq_homes(owner_id) values (v_owner) on conflict do nothing;
  -- Serialize initialization/reset against another tab. Ordinary initialization
  -- never changes rows a user already edited; only explicit replacement does.
  select * into v_home from public.homehq_homes where owner_id = v_owner for update;
  if exists (select 1 from public.homehq_people where owner_id = v_owner) and not p_replace then
    return public.homehq_snapshot();
  end if;
  if p_replace then
    delete from public.homehq_event_people where owner_id = v_owner;
    delete from public.homehq_events where owner_id = v_owner;
    delete from public.homehq_checklist where owner_id = v_owner;
    delete from public.homehq_devices where owner_id = v_owner;
    delete from public.homehq_cards where owner_id = v_owner;
    delete from public.homehq_photos where owner_id = v_owner;
    delete from public.homehq_people where owner_id = v_owner;
  end if;
  v_today := (now() at time zone v_home.timezone)::date;
  for v_row, v_i in select value, ordinality::integer from jsonb_array_elements(v_fixture->'people') with ordinality loop
    insert into public.homehq_people(owner_id,id,name,color,home,status,eta,sort_order) values (
      v_owner,v_row->>'id',v_row->>'name',v_row->>'color',(v_row->>'home')::boolean,
      v_row->>'status',(v_row->>'eta')::integer,v_i
    );
  end loop;
  for v_row in select value from jsonb_array_elements(v_fixture->'events') loop
    insert into public.homehq_events(owner_id,id,starts_at,ends_at,title,travel,loc,notes,all_day) values (
      v_owner,v_row->>'id',
      ((to_timestamp((v_row->>'start')::bigint) at time zone 'America/Toronto')
        + (v_today - date '2026-10-11') * interval '1 day') at time zone v_home.timezone,
      ((to_timestamp((v_row->>'end')::bigint) at time zone 'America/Toronto')
        + (v_today - date '2026-10-11') * interval '1 day') at time zone v_home.timezone,
      v_row->>'title',(v_row->>'travel')::integer,v_row->>'loc',v_row->>'notes',(v_row->>'all_day')::boolean
    );
    for v_person in select jsonb_array_elements_text(v_row->'people') loop
      insert into public.homehq_event_people(owner_id,event_id,person_id) values (v_owner,v_row->>'id',v_person);
    end loop;
  end loop;
  for v_row, v_i in select value, ordinality::integer from jsonb_array_elements(v_fixture->'chores') with ordinality loop
    insert into public.homehq_checklist(owner_id,kind,id,title,person_id,routine,stars,done,done_by,sort_order) values (
      v_owner,'chore',v_row->>'id',v_row->>'title',nullif(v_row->>'who','any'),v_row->>'routine',
      (v_row->>'stars')::integer,(v_row->>'done')::boolean,v_row->>'done_by',v_i
    );
  end loop;
  for v_row, v_i in select value, ordinality::integer from jsonb_array_elements(v_fixture->'shopping') with ordinality loop
    insert into public.homehq_checklist(owner_id,kind,id,title,category,store,quantity,note,done,sort_order) values (
      v_owner,'shopping',v_row->>'id',v_row->>'name',v_row->>'category',v_row->>'store',
      (v_row->>'quantity')::integer,v_row->>'note',(v_row->>'done')::boolean,v_i
    );
  end loop;
  for v_row, v_i in select value, ordinality::integer from jsonb_array_elements(v_fixture->'devices') with ordinality loop
    insert into public.homehq_devices(owner_id,id,name,room,type,on_state,level,locked,garage_state,sort_order) values (
      v_owner,v_row->>'id',v_row->>'name',v_row->>'room',v_row->>'type',
      (v_row->>'on')::boolean,(v_row->>'level')::integer,(v_row->>'locked')::boolean,v_row->>'state',v_i
    );
  end loop;
  for v_row, v_i in select value, ordinality::integer from jsonb_array_elements(v_fixture->'photos') with ordinality loop
    insert into public.homehq_photos(owner_id,id,path,asset,caption,place,sort_order) values (
      v_owner,v_row->>'id',v_row->>'path',v_row->>'asset',v_row->>'caption',v_row->>'place',v_i
    );
  end loop;
  insert into public.homehq_cards(owner_id,section,data) values
    (v_owner,'weather',v_fixture->'weather'),
    (v_owner,'home_status',v_fixture->'home_status'),
    (v_owner,'agents',v_fixture->'agents');
  return public.homehq_snapshot();
end;
$function$;

REVOKE ALL ON FUNCTION "public"."homehq_seed_demo"(boolean) FROM PUBLIC, "anon";

CREATE OR REPLACE FUNCTION public.homehq_set_device (
  p_id      text,
  p_state   jsonb,
  p_version bigint
)
  RETURNS jsonb
  LANGUAGE plpgsql
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid := auth.uid();
  v_device public.homehq_devices;
  v_state jsonb;
  v_keys text[];
  v_status text := 'saved';
  v_revision bigint;
begin
  if v_owner is null then raise exception using errcode = '42501', message = 'Sign in to Home HQ'; end if;
  if p_id is null or p_version is null or p_version < 1 or p_state is null
    or jsonb_typeof(p_state) <> 'object' or p_state = '{}'::jsonb then
    raise exception using errcode = '22023', message = 'Invalid device command';
  end if;
  select * into v_device from public.homehq_devices where owner_id = v_owner and id = p_id for update;
  if not found then raise exception using errcode = 'PT404', message = 'Device not found'; end if;
  v_keys := case v_device.type when 'light' then array['on', 'level'] when 'lock' then array['locked'] else array['state'] end;
  if exists (select 1 from jsonb_object_keys(p_state) k where not (k = any(v_keys)))
    or (p_state ? 'on' and jsonb_typeof(p_state->'on') <> 'boolean')
    or (p_state ? 'locked' and jsonb_typeof(p_state->'locked') <> 'boolean')
    or (p_state ? 'level' and (jsonb_typeof(p_state->'level') <> 'number'
      or (p_state->>'level') !~ '^[0-9]{1,3}$' or (p_state->>'level')::numeric > 100))
    or (p_state ? 'state' and (jsonb_typeof(p_state->'state') <> 'string'
      or p_state->>'state' not in ('open', 'closed'))) then
    raise exception using errcode = '22023', message = 'State is invalid for this sample device';
  end if;
  v_state := case v_device.type
    when 'light' then jsonb_build_object('on', v_device.on_state, 'level', v_device.level)
    when 'lock' then jsonb_build_object('locked', v_device.locked)
    else jsonb_build_object('state', v_device.garage_state) end;
  if v_state @> p_state then
    null;
  elsif v_device.version <> p_version then
    v_status := 'conflict';
  else
    update public.homehq_devices set
      on_state = case when p_state ? 'on' then (p_state->>'on')::boolean else on_state end,
      level = case when p_state ? 'level' then (p_state->>'level')::integer else level end,
      locked = case when p_state ? 'locked' then (p_state->>'locked')::boolean else locked end,
      garage_state = case when p_state ? 'state' then p_state->>'state' else garage_state end
      where owner_id = v_owner and id = p_id returning * into v_device;
  end if;
  select revision into v_revision from public.homehq_homes where owner_id = v_owner;
  return jsonb_build_object('status', v_status, 'item', homehq_private.device_json(v_device), 'revision', v_revision);
end;
$function$;

REVOKE ALL ON FUNCTION "public"."homehq_set_device"(text, jsonb, bigint) FROM PUBLIC, "anon";

CREATE OR REPLACE FUNCTION public.homehq_set_done (
  p_kind    text,
  p_id      text,
  p_done    boolean,
  p_version bigint,
  p_done_by text    DEFAULT NULL::text
)
  RETURNS jsonb
  LANGUAGE plpgsql
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid := auth.uid();
  v_item public.homehq_checklist;
  v_done_by text;
  v_status text := 'saved';
  v_revision bigint;
begin
  if v_owner is null then raise exception using errcode = '42501', message = 'Sign in to Home HQ'; end if;
  if p_kind is null or p_kind not in ('chore', 'shopping') or p_id is null or p_done is null
    or p_version is null or p_version < 1 then
    raise exception using errcode = '22023', message = 'Invalid checklist command';
  end if;
  select * into v_item from public.homehq_checklist
    where owner_id = v_owner and kind = p_kind and id = p_id for update;
  if not found then raise exception using errcode = 'PT404', message = 'Checklist item not found'; end if;
  if p_kind = 'shopping' and p_done_by is not null then
    raise exception using errcode = '22023', message = 'Shopping does not take done_by';
  end if;
  if p_kind = 'chore' and p_done then
    v_done_by := coalesce(v_item.person_id, p_done_by);
    if v_done_by is null or (p_done_by is not null and v_item.person_id is not null and p_done_by <> v_item.person_id)
      or not exists (select 1 from public.homehq_people where owner_id = v_owner and id = v_done_by) then
      raise exception using errcode = '22023', message = 'Choose the person completing this chore';
    end if;
  elsif p_done_by is not null then
    raise exception using errcode = '22023', message = 'An undone chore does not take done_by';
  end if;

  -- Compare under one row lock. Two clients cannot both apply contradictory
  -- states against the same version. Matching state succeeds without another
  -- update, so retrying a lost HTTP response cannot add stars or a new version.
  if v_item.done = p_done and v_item.done_by is not distinct from v_done_by then
    null;
  elsif v_item.version <> p_version then
    v_status := 'conflict';
  else
    update public.homehq_checklist set done = p_done, done_by = v_done_by
      where owner_id = v_owner and kind = p_kind and id = p_id returning * into v_item;
  end if;
  select revision into v_revision from public.homehq_homes where owner_id = v_owner;
  return jsonb_build_object('status', v_status, 'item', homehq_private.item_json(v_item), 'revision', v_revision);
end;
$function$;

REVOKE ALL ON FUNCTION "public"."homehq_set_done"(text, text, boolean, bigint, text) FROM PUBLIC, "anon";

CREATE OR REPLACE FUNCTION public.homehq_snapshot()
  RETURNS jsonb
  LANGUAGE plpgsql
  STABLE
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid := auth.uid();
  v_home public.homehq_homes;
  v_today date;
  v_start timestamptz;
  v_end timestamptz;
  v_result jsonb;
begin
  if v_owner is null then raise exception using errcode = '42501', message = 'Sign in to Home HQ'; end if;
  select * into v_home from public.homehq_homes where owner_id = v_owner;
  if not found then raise exception using errcode = 'PT404', message = 'Initialize Home HQ first'; end if;
  v_today := (now() at time zone v_home.timezone)::date;
  v_start := v_today::timestamp at time zone v_home.timezone;
  v_end := (v_today + 7)::timestamp at time zone v_home.timezone;

  -- Refuse an oversized home instead of silently hiding calendar/checklist rows.
  -- This whole response must fit a bounded MicroPython HTTP allocation.
  if (select count(*) from public.homehq_people where owner_id = v_owner) > 8
    or (select count(*) from public.homehq_events where owner_id = v_owner and ends_at > v_start and starts_at < v_end) > 64
    or (select count(*) from public.homehq_checklist where owner_id = v_owner and kind = 'chore') > 64
    or (select count(*) from public.homehq_checklist where owner_id = v_owner and kind = 'shopping') > 64
    or (select count(*) from public.homehq_devices where owner_id = v_owner) > 16
    or (select count(*) from public.homehq_photos where owner_id = v_owner) > 20 then
    raise exception using errcode = '22023', message = 'Home HQ display row limit exceeded';
  end if;

  select jsonb_build_object(
    'schema_version', 1, 'revision', v_home.revision,
    'server_time', floor(extract(epoch from now()))::bigint,
    'home', jsonb_build_object('title', v_home.title, 'timezone', v_home.timezone, 'demo', v_home.demo,
      'utc_offset_minutes', extract(epoch from ((now() at time zone v_home.timezone) - (now() at time zone 'UTC')))::integer / 60),
    'people', coalesce((select jsonb_agg(jsonb_build_object(
      'id', p.id, 'name', p.name, 'color', p.color, 'home', p.home, 'status', p.status, 'eta', p.eta
    ) order by p.sort_order, p.id) from public.homehq_people p where p.owner_id = v_owner), '[]'::jsonb),
    'events', coalesce((select jsonb_agg(jsonb_build_object(
      'id', e.id, 'start', floor(extract(epoch from e.starts_at))::bigint, 'end', floor(extract(epoch from e.ends_at))::bigint,
      'title', e.title, 'travel', e.travel, 'loc', e.loc, 'notes', e.notes, 'all_day', e.all_day,
      'people', coalesce((select jsonb_agg(ep.person_id order by ep.person_id)
        from public.homehq_event_people ep where ep.owner_id = v_owner and ep.event_id = e.id), '[]'::jsonb)
    ) order by e.starts_at, e.id) from public.homehq_events e
      where e.owner_id = v_owner and e.ends_at > v_start and e.starts_at < v_end), '[]'::jsonb),
    'chores', coalesce((select jsonb_agg(homehq_private.item_json(c) order by c.sort_order, c.id)
      from public.homehq_checklist c where c.owner_id = v_owner and c.kind = 'chore'), '[]'::jsonb),
    'shopping', coalesce((select jsonb_agg(homehq_private.item_json(c) order by c.sort_order, c.id)
      from public.homehq_checklist c where c.owner_id = v_owner and c.kind = 'shopping'), '[]'::jsonb),
    'devices', coalesce((select jsonb_agg(homehq_private.device_json(d) order by d.sort_order, d.id)
      from public.homehq_devices d where d.owner_id = v_owner), '[]'::jsonb),
    'photos', coalesce((select jsonb_agg(jsonb_build_object(
      'id', p.id, 'path', p.path, 'asset', p.asset, 'caption', p.caption, 'place', p.place
    ) order by p.sort_order, p.id) from public.homehq_photos p where p.owner_id = v_owner), '[]'::jsonb),
    'weather', coalesce((select data from public.homehq_cards where owner_id = v_owner and section = 'weather'), '{}'::jsonb),
    'home_status', coalesce((select data from public.homehq_cards where owner_id = v_owner and section = 'home_status'), '{}'::jsonb)
      || jsonb_build_object('lights_on', (select count(*) from public.homehq_devices where owner_id = v_owner and type = 'light' and on_state),
        'locked', coalesce((select bool_and(locked) from public.homehq_devices where owner_id = v_owner and type = 'lock'), true), 'sample', true),
    'agents', coalesce((select data from public.homehq_cards where owner_id = v_owner and section = 'agents'), '[]'::jsonb)
  ) into v_result;
  if octet_length(v_result::text) > 32768 then
    raise exception using errcode = '22023', message = 'Home HQ snapshot exceeds 32 KiB';
  end if;
  return v_result;
end;
$function$;

REVOKE ALL ON FUNCTION "public"."homehq_snapshot"() FROM PUBLIC, "anon";

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE ON public.homehq_cards
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('cards');

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE ON public.homehq_checklist
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('checklist');

CREATE TRIGGER homehq_checklist_version
  BEFORE UPDATE ON public.homehq_checklist
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.bump_version();

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE ON public.homehq_devices
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('devices');

CREATE TRIGGER homehq_device_version
  BEFORE UPDATE ON public.homehq_devices
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.bump_version();

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE ON public.homehq_event_people
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('events');

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE ON public.homehq_events
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('events');

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE OF title, timezone, demo ON public.homehq_homes
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('home');

CREATE TRIGGER homehq_validate_home
  BEFORE INSERT OR UPDATE OF title, timezone, demo ON public.homehq_homes
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.validate_home();

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE ON public.homehq_people
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('people');

CREATE TRIGGER homehq_changed
  AFTER INSERT OR DELETE OR UPDATE ON public.homehq_photos
  FOR EACH ROW
  EXECUTE FUNCTION homehq_private.broadcast_change('photos');

CREATE POLICY "homehq_receive" ON "realtime"."messages"
  FOR SELECT
  TO "authenticated"
  USING (((EXTENSION = 'broadcast'::text) AND (( SELECT auth.uid() AS uid) IS
    NOT NULL) AND (( SELECT realtime.topic() AS topic) = ('homehq:'::text || (( SELECT auth.uid() AS uid))::text)) AND
    (topic = ('homehq:'::text || (( SELECT auth.uid() AS uid))::text))));

CREATE POLICY "homehq_photo_delete" ON "storage"."objects"
  FOR DELETE
  TO "authenticated"
  USING (((bucket_id = 'homehq-photos'::text) AND ((storage.foldername(name))[1] = (( SELECT auth.uid() AS uid))::text)));

CREATE POLICY "homehq_photo_insert" ON "storage"."objects"
  FOR INSERT
  TO "authenticated"
  WITH CHECK (((bucket_id = 'homehq-photos'::text) AND (name ~ (('^'::text || (( SELECT auth.uid() AS uid))::text) || '/[0-9a-f]{64}\.png$'::text))));

CREATE POLICY "homehq_photo_read" ON "storage"."objects"
  FOR SELECT
  TO "authenticated"
  USING (((bucket_id = 'homehq-photos'::text) AND ((storage.foldername(name))[1] = (( SELECT auth.uid() AS uid))::text)));

CREATE POLICY "homehq_photo_update" ON "storage"."objects"
  FOR UPDATE
  TO "authenticated"
  USING (((bucket_id = 'homehq-photos'::text) AND ((storage.foldername(name))[1] = (( SELECT auth.uid() AS uid))::text)))
  WITH CHECK (((bucket_id = 'homehq-photos'::text) AND (name ~ (('^'::text || (( SELECT auth.uid() AS uid))::text) || '/[0-9a-f]{64}\.png$'::text))));

REVOKE ALL ON FUNCTION "homehq_private"."broadcast_change"() FROM PUBLIC;

REVOKE ALL ON FUNCTION "homehq_private"."bump_version"() FROM PUBLIC;

REVOKE ALL ON FUNCTION "homehq_private"."device_json"(public.homehq_devices) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION "homehq_private"."device_json"(public.homehq_devices) TO "authenticated";

REVOKE ALL ON FUNCTION "homehq_private"."item_json"(public.homehq_checklist) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION "homehq_private"."item_json"(public.homehq_checklist) TO "authenticated";

REVOKE ALL ON FUNCTION "homehq_private"."validate_home"() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION "public"."homehq_seed_demo"(boolean) TO "authenticated";

REVOKE ALL ON FUNCTION "public"."homehq_seed_demo"(boolean) FROM "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_seed_demo"(boolean) TO "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_seed_demo"(boolean) TO "service_role";

GRANT EXECUTE ON FUNCTION "public"."homehq_set_device"(text, jsonb, bigint) TO "authenticated";

REVOKE ALL ON FUNCTION "public"."homehq_set_device"(text, jsonb, bigint) FROM "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_set_device"(text, jsonb, bigint) TO "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_set_device"(text, jsonb, bigint) TO "service_role";

GRANT EXECUTE ON FUNCTION "public"."homehq_set_done"(text, text, boolean, bigint, text) TO "authenticated";

REVOKE ALL ON FUNCTION "public"."homehq_set_done"(text, text, boolean, bigint, text) FROM "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_set_done"(text, text, boolean, bigint, text) TO "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_set_done"(text, text, boolean, bigint, text) TO "service_role";

GRANT EXECUTE ON FUNCTION "public"."homehq_snapshot"() TO "authenticated";

REVOKE ALL ON FUNCTION "public"."homehq_snapshot"() FROM "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_snapshot"() TO "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_snapshot"() TO "service_role";

GRANT USAGE ON SCHEMA "homehq_private" TO "authenticated";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_cards" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_cards" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_cards" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_cards" TO "service_role";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_checklist" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_checklist" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_checklist" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_checklist" TO "service_role";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_devices" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_devices" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_devices" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_devices" TO "service_role";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_event_people" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_event_people" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_event_people" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_event_people" TO "service_role";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_events" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_events" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_events" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_events" TO "service_role";

REVOKE ALL ("demo") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("demo"), UPDATE ("demo") ON TABLE "public"."homehq_homes" TO "authenticated";

REVOKE ALL ("timezone") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("timezone"), UPDATE ("timezone") ON TABLE "public"."homehq_homes" TO "authenticated";

REVOKE ALL ("title") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("title"), UPDATE ("title") ON TABLE "public"."homehq_homes" TO "authenticated";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_homes" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_homes" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_homes" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_homes" TO "service_role";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_people" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_people" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_people" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_people" TO "service_role";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_photos" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_photos" FROM "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_photos" TO "postgres";

GRANT DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE ON TABLE "public"."homehq_photos" TO "service_role";

CREATE POLICY "homehq_owner" ON "public"."homehq_cards"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));

CREATE INDEX homehq_checklist_done_by ON public.homehq_checklist USING btree (owner_id, done_by);

CREATE INDEX homehq_checklist_person ON public.homehq_checklist USING btree (owner_id, person_id);

CREATE POLICY "homehq_owner" ON "public"."homehq_checklist"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));

CREATE POLICY "homehq_owner" ON "public"."homehq_devices"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));

CREATE INDEX homehq_event_people_person ON public.homehq_event_people USING btree (owner_id, person_id);

CREATE POLICY "homehq_owner" ON "public"."homehq_event_people"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));

ALTER TABLE "public"."homehq_event_people"
  ADD CONSTRAINT "homehq_event_people_owner_id_event_id_fkey" FOREIGN KEY (owner_id, event_id) REFERENCES public.homehq_events(owner_id, id) ON DELETE CASCADE;

CREATE INDEX homehq_events_owner_time ON public.homehq_events USING btree (owner_id, starts_at);

CREATE POLICY "homehq_owner" ON "public"."homehq_events"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));

ALTER TABLE "public"."homehq_homes"
  ADD CONSTRAINT "homehq_homes_owner_id_fkey" FOREIGN KEY (owner_id) REFERENCES auth.users(id) ON DELETE CASCADE;

ALTER TABLE "public"."homehq_cards"
  ADD CONSTRAINT "homehq_cards_owner_id_fkey" FOREIGN KEY (owner_id) REFERENCES public.homehq_homes(owner_id) ON DELETE CASCADE;

ALTER TABLE "public"."homehq_checklist"
  ADD CONSTRAINT "homehq_checklist_owner_id_fkey" FOREIGN KEY (owner_id) REFERENCES public.homehq_homes(owner_id) ON DELETE CASCADE;

ALTER TABLE "public"."homehq_devices"
  ADD CONSTRAINT "homehq_devices_owner_id_fkey" FOREIGN KEY (owner_id) REFERENCES public.homehq_homes(owner_id) ON DELETE CASCADE;

ALTER TABLE "public"."homehq_events"
  ADD CONSTRAINT "homehq_events_owner_id_fkey" FOREIGN KEY (owner_id) REFERENCES public.homehq_homes(owner_id) ON DELETE CASCADE;

CREATE POLICY "homehq_owner" ON "public"."homehq_homes"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));

REVOKE ALL ("owner_id") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("owner_id") ON TABLE "public"."homehq_homes" TO "authenticated";

ALTER TABLE "public"."homehq_people"
  ADD CONSTRAINT "homehq_people_owner_id_fkey" FOREIGN KEY (owner_id) REFERENCES public.homehq_homes(owner_id) ON DELETE CASCADE;

ALTER TABLE "public"."homehq_checklist"
  ADD CONSTRAINT "homehq_checklist_owner_id_done_by_fkey" FOREIGN KEY (owner_id, done_by) REFERENCES public.homehq_people(owner_id, id);

ALTER TABLE "public"."homehq_checklist"
  ADD CONSTRAINT "homehq_checklist_owner_id_person_id_fkey" FOREIGN KEY (owner_id, person_id) REFERENCES public.homehq_people(owner_id, id);

ALTER TABLE "public"."homehq_event_people"
  ADD CONSTRAINT "homehq_event_people_owner_id_person_id_fkey" FOREIGN KEY (owner_id, person_id) REFERENCES public.homehq_people(owner_id, id) ON DELETE CASCADE;

CREATE POLICY "homehq_owner" ON "public"."homehq_people"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));

ALTER TABLE "public"."homehq_photos"
  ADD CONSTRAINT "homehq_photos_owner_id_fkey" FOREIGN KEY (owner_id) REFERENCES public.homehq_homes(owner_id) ON DELETE CASCADE;

CREATE POLICY "homehq_owner" ON "public"."homehq_photos"
  FOR ALL
  TO "authenticated"
  USING ((( SELECT auth.uid() AS uid) = owner_id))
  WITH CHECK ((( SELECT auth.uid() AS uid) = owner_id));
