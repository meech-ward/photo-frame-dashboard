SET local check_function_bodies = off;

ALTER TABLE "public"."homehq_photos"
  ADD COLUMN "web_path" text;

ALTER TABLE "public"."homehq_photos"
  ADD COLUMN "web_width" integer;

ALTER TABLE "public"."homehq_photos"
  ADD COLUMN "web_height" integer;

CREATE OR REPLACE FUNCTION public.homehq_snapshot()
  RETURNS jsonb
  LANGUAGE plpgsql
  STABLE
  SET search_path TO ''
  AS $function$
declare
  v_result jsonb := public.homehq_web_snapshot();
  v_today date := (now() at time zone (v_result->'home'->>'timezone'))::date;
  v_start timestamptz := v_today::timestamp at time zone (v_result->'home'->>'timezone');
  v_end timestamptz := (v_today + 7)::timestamp at time zone (v_result->'home'->>'timezone');
  v_key text;
  v_limit integer;
  v_rows jsonb;
  v_index integer;
  v_truncated jsonb := '[]'::jsonb;
begin
  -- Older clients treat a missing editable row as deleted and discard its
  -- pending writes. Never trim people/checklists/devices: an oversized editable
  -- collection must keep the previous explicit error and cached device state.
  if jsonb_array_length(v_result->'people') > 8
    or jsonb_array_length(v_result->'chores') > 64
    or jsonb_array_length(v_result->'shopping') > 64
    or jsonb_array_length(v_result->'devices') > 16 then
    raise exception using errcode = '22023', message = 'Home HQ display row limit exceeded';
  end if;
  -- Read-only collections can narrow safely as the full web household grows.
  select coalesce(jsonb_agg(value order by ordinal), '[]'::jsonb) into v_rows
    from jsonb_array_elements(v_result->'events') with ordinality as rows(value, ordinal)
    where (value->>'end')::bigint > extract(epoch from v_start)
      and (value->>'start')::bigint < extract(epoch from v_end);
  v_result := jsonb_set(v_result, '{events}', v_rows);
  select coalesce(jsonb_agg(value - array['web_path','web_width','web_height'] order by ordinal), '[]'::jsonb) into v_rows
    from jsonb_array_elements(v_result->'photos') with ordinality as rows(value, ordinal);
  v_result := jsonb_set(v_result, '{photos}', v_rows);

  for v_key, v_limit in select key, value::text::integer from jsonb_each(
    '{"events":64,"photos":20}'::jsonb)
  loop
    if jsonb_array_length(v_result->v_key) > v_limit then
      -- Earliest events and the first photos in authored order stay visible.
      select jsonb_agg(value order by ordinal) into v_rows from (
        select value, ordinal from jsonb_array_elements(v_result->v_key) with ordinality as rows(value, ordinal)
        order by ordinal limit v_limit
      ) selected;
      v_result := jsonb_set(v_result, array[v_key], v_rows);
      v_truncated := v_truncated || jsonb_build_array(v_key);
    end if;
  end loop;
  if v_truncated <> '[]'::jsonb then
    v_result := jsonb_set(v_result, '{truncated}', v_truncated);
  end if;

  -- Count limits alone cannot bound UTF-8 bytes. Remove the last row from the
  -- largest read-only collection until the response fits. Never hide an editable
  -- row from an installed client's outbox; fail safely if those fields alone
  -- exhaust its HTTP allocation. Each iteration removes a row or raises.
  while octet_length(v_result::text) > 32768 loop
    select key into v_key from unnest(array['events','photos','agents']) as sections(key)
      where jsonb_array_length(v_result->key) > 0
      order by octet_length((v_result->key)::text) desc, key limit 1;
    if v_key is null then
      raise exception using errcode = '22023', message = 'Home HQ snapshot exceeds 32 KiB';
    end if;
    select (ordinal - 1)::integer into v_index
      from jsonb_array_elements(v_result->v_key) with ordinality as rows(value, ordinal)
      order by ordinal desc limit 1;
    v_result := jsonb_set(v_result, array[v_key], (v_result->v_key) - v_index);
    if not v_truncated ? v_key then v_truncated := v_truncated || jsonb_build_array(v_key); end if;
    v_result := jsonb_set(v_result, '{truncated}', v_truncated);
  end loop;
  return v_result;
end;
$function$;

CREATE OR REPLACE FUNCTION public.homehq_web_snapshot()
  RETURNS jsonb
  LANGUAGE plpgsql
  STABLE
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid := homehq_private.current_home_id();
  v_home public.homehq_homes;
  v_result jsonb;
begin
  if v_owner is null then raise exception using errcode = '42501', message = 'Sign in to Home HQ'; end if;
  select * into v_home from public.homehq_homes where owner_id = v_owner;
  if not found then raise exception using errcode = 'PT404', message = 'Initialize Home HQ first'; end if;
  select jsonb_build_object(
    'schema_version', 1, 'revision', v_home.revision,
    'server_time', floor(extract(epoch from now()))::bigint,
    'home', jsonb_build_object('id', v_home.owner_id, 'title', v_home.title, 'timezone', v_home.timezone, 'demo', v_home.demo,
      'utc_offset_minutes', homehq_private.utc_offset_minutes(now(), v_home.timezone)),
    'viewer', jsonb_build_object('user_id', auth.uid(), 'is_owner', v_owner = auth.uid(),
      'person_id', (select person_id from public.homehq_members where user_id = auth.uid())),
    'members', coalesce((select jsonb_agg(jsonb_build_object('user_id', user_id, 'person_id', person_id) order by person_id)
      from public.homehq_members where owner_id = v_owner), '[]'::jsonb),
    'people', coalesce((select jsonb_agg(jsonb_build_object(
      'id', p.id, 'name', p.name, 'color', p.color, 'home', p.home, 'status', p.status, 'eta', p.eta
    ) order by p.sort_order, p.id) from public.homehq_people p where p.owner_id = v_owner), '[]'::jsonb),
    'events', coalesce((select jsonb_agg(jsonb_build_object(
      'id', e.id, 'start', floor(extract(epoch from e.starts_at))::bigint, 'end', floor(extract(epoch from e.ends_at))::bigint,
      'start_offset_minutes', homehq_private.utc_offset_minutes(e.starts_at, v_home.timezone),
      'end_offset_minutes', homehq_private.utc_offset_minutes(e.ends_at, v_home.timezone),
      'title', e.title, 'travel', e.travel, 'loc', e.loc, 'notes', e.notes, 'all_day', e.all_day,
      'people', coalesce((select jsonb_agg(ep.person_id order by ep.person_id)
        from public.homehq_event_people ep where ep.owner_id = v_owner and ep.event_id = e.id), '[]'::jsonb)
    ) order by e.starts_at, e.id) from public.homehq_events e
      where e.owner_id = v_owner), '[]'::jsonb),
    'chores', coalesce((select jsonb_agg(homehq_private.item_json(c) order by c.sort_order, c.id)
      from public.homehq_checklist c where c.owner_id = v_owner and c.kind = 'chore'), '[]'::jsonb),
    'shopping', coalesce((select jsonb_agg(homehq_private.item_json(c) order by c.sort_order, c.id)
      from public.homehq_checklist c where c.owner_id = v_owner and c.kind = 'shopping'), '[]'::jsonb),
    'devices', coalesce((select jsonb_agg(homehq_private.device_json(d) order by d.sort_order, d.id)
      from public.homehq_devices d where d.owner_id = v_owner), '[]'::jsonb),
    'photos', coalesce((select jsonb_agg(jsonb_build_object(
      'id', p.id, 'path', p.path, 'asset', p.asset, 'caption', p.caption, 'place', p.place
    ) || jsonb_strip_nulls(jsonb_build_object('jpeg_path', p.jpeg_path, 'web_path', p.web_path, 'web_width', p.web_width, 'web_height', p.web_height))
      order by p.sort_order, p.id) from public.homehq_photos p where p.owner_id = v_owner), '[]'::jsonb),
    'weather', coalesce((select data from public.homehq_cards where owner_id = v_owner and section = 'weather'), '{}'::jsonb),
    'home_status', coalesce((select data from public.homehq_cards where owner_id = v_owner and section = 'home_status'), '{}'::jsonb)
      || jsonb_build_object('lights_on', (select count(*) from public.homehq_devices where owner_id = v_owner and type = 'light' and on_state),
        'locked', coalesce((select bool_and(locked) from public.homehq_devices where owner_id = v_owner and type = 'lock'), true), 'sample', true),
    'agents', coalesce((select data from public.homehq_cards where owner_id = v_owner and section = 'agents'), '[]'::jsonb)
  ) into v_result;
  return v_result;
end;
$function$;

REVOKE ALL ON FUNCTION "public"."homehq_web_snapshot"() FROM PUBLIC, "anon";

ALTER TABLE "public"."homehq_photos"
  ADD CONSTRAINT "homehq_photos_web_dimensions_check" CHECK ((((web_width IS NULL) AND (web_height IS NULL)) OR ((web_path IS NOT NULL) AND (web_width IS
    NOT NULL) AND (web_height IS NOT NULL) AND ((web_width >= 1) AND (web_width <= 2048)) AND ((web_height >= 1) AND (web_height <= 2048)))));

ALTER TABLE "public"."homehq_photos"
  ADD CONSTRAINT "homehq_photos_web_path_check" CHECK (((web_path IS NULL) OR ((path IS
    NOT NULL) AND (web_path ~ (('^'::text || (owner_id)::text) || '/[0-9a-f]{64}\.jpg$'::text)))));

GRANT EXECUTE ON FUNCTION "public"."homehq_web_snapshot"() TO "authenticated";

REVOKE ALL ON FUNCTION "public"."homehq_web_snapshot"() FROM "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_web_snapshot"() TO "postgres";

GRANT EXECUTE ON FUNCTION "public"."homehq_web_snapshot"() TO "service_role";
