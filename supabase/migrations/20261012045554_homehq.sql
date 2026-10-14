SET local check_function_bodies = off;

ALTER TABLE "public"."homehq_checklist"
  DROP CONSTRAINT "homehq_checklist_id_check";

ALTER TABLE "public"."homehq_devices"
  DROP CONSTRAINT "homehq_devices_id_check";

ALTER TABLE "public"."homehq_events"
  DROP CONSTRAINT "homehq_events_id_check";

ALTER TABLE "public"."homehq_people"
  DROP CONSTRAINT "homehq_people_id_check";

ALTER TABLE "public"."homehq_photos"
  DROP CONSTRAINT "homehq_photos_id_check";

CREATE OR REPLACE FUNCTION public.homehq_save_event (
  p_id      text,
  p_title   text,
  p_start   bigint,
  p_end     bigint,
  p_people  text[],
  p_loc     text    DEFAULT ''::text,
  p_notes   text    DEFAULT ''::text,
  p_travel  integer DEFAULT 0,
  p_all_day boolean DEFAULT false
)
  RETURNS jsonb
  LANGUAGE plpgsql
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid := auth.uid();
  v_event public.homehq_events;
begin
  if v_owner is null then raise exception using errcode = '42501', message = 'Sign in to Home HQ'; end if;
  if p_id is null or p_title is null or p_start is null or p_end is null or p_end < p_start
    or p_start < 0 or p_end > 7258118400 or p_people is null or cardinality(p_people) > 8
    or p_loc is null or p_notes is null or p_travel is null or p_all_day is null then
    raise exception using errcode = '22023', message = 'Invalid calendar event';
  end if;
  if exists (select 1 from unnest(p_people) person_id
    where person_id is null or not exists (select 1 from public.homehq_people p where p.owner_id = v_owner and p.id = person_id)) then
    raise exception using errcode = '22023', message = 'Choose people from this home';
  end if;
  -- The attendee replacement and event edit share a transaction. A failed person
  -- relation cannot leave a saved event with its previous attendees removed.
  insert into public.homehq_events(owner_id, id, starts_at, ends_at, title, loc, notes, travel, all_day)
    values (v_owner, p_id, to_timestamp(p_start), to_timestamp(p_end), p_title, p_loc, p_notes, p_travel, p_all_day)
    on conflict (owner_id, id) do update set starts_at = excluded.starts_at, ends_at = excluded.ends_at,
      title = excluded.title, loc = excluded.loc, notes = excluded.notes, travel = excluded.travel, all_day = excluded.all_day
    returning * into v_event;
  delete from public.homehq_event_people where owner_id = v_owner and event_id = p_id;
  insert into public.homehq_event_people(owner_id, event_id, person_id)
    select v_owner, p_id, person_id from (select distinct unnest(p_people) person_id) people;
  return jsonb_build_object(
    'id', v_event.id, 'title', v_event.title, 'start', floor(extract(epoch from v_event.starts_at))::bigint,
    'end', floor(extract(epoch from v_event.ends_at))::bigint, 'people', to_jsonb(p_people),
    'loc', v_event.loc, 'notes', v_event.notes, 'travel', v_event.travel, 'all_day', v_event.all_day
  );
end;
$function$;

REVOKE ALL ON FUNCTION "public"."homehq_save_event"(text, text, bigint, bigint, text[], text, text, integer, boolean) FROM PUBLIC, "anon";

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
    or (p_state ? 'state' and (jsonb_typeof(p_state->'state') <> 'string'
      or p_state->>'state' not in ('open', 'closed'))) then
    raise exception using errcode = '22023', message = 'State is invalid for this sample device';
  end if;
  if p_state ? 'level' then
    if jsonb_typeof(p_state->'level') <> 'number' or (p_state->>'level') !~ '^[0-9]{1,3}$' then
      raise exception using errcode = '22023', message = 'Light level must be an integer from 0 to 100';
    end if;
    if (p_state->>'level')::integer > 100 then
      raise exception using errcode = '22023', message = 'Light level must be an integer from 0 to 100';
    end if;
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

ALTER TABLE "public"."homehq_checklist"
  ADD CONSTRAINT "homehq_checklist_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,64}$'::text));

ALTER TABLE "public"."homehq_devices"
  ADD CONSTRAINT "homehq_devices_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,64}$'::text));

ALTER TABLE "public"."homehq_events"
  ADD CONSTRAINT "homehq_events_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,64}$'::text));

ALTER TABLE "public"."homehq_people"
  ADD CONSTRAINT "homehq_people_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,64}$'::text));

ALTER TABLE "public"."homehq_photos"
  ADD CONSTRAINT "homehq_photos_id_check" CHECK ((id ~ '^[a-z0-9_-]{1,64}$'::text));

GRANT EXECUTE ON FUNCTION "public"."homehq_save_event"(text, text, bigint, bigint, text[], text, text, integer, boolean) TO "authenticated";

REVOKE ALL ON FUNCTION "public"."homehq_save_event"(text, text, bigint, bigint, text[], text, text, integer, boolean) FROM "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_save_event"(text, text, bigint, bigint, text[], text, text, integer, boolean) TO "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_save_event"(text, text, bigint, bigint, text[], text, text, integer, boolean) TO "service_role";
