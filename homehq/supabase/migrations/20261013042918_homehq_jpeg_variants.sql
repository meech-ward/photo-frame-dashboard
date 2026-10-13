SET local check_function_bodies = off;

DROP POLICY "homehq_photo_insert" ON "storage"."objects";

DROP POLICY "homehq_photo_update" ON "storage"."objects";

ALTER TABLE "public"."homehq_photos"
  ADD COLUMN "jpeg_path" text;

CREATE OR REPLACE FUNCTION public.homehq_snapshot()
  RETURNS jsonb
  LANGUAGE plpgsql
  STABLE
  SET search_path TO ''
  AS $function$
declare
  v_owner uuid := homehq_private.current_home_id();
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
      where e.owner_id = v_owner and e.ends_at > v_start and e.starts_at < v_end), '[]'::jsonb),
    'chores', coalesce((select jsonb_agg(homehq_private.item_json(c) order by c.sort_order, c.id)
      from public.homehq_checklist c where c.owner_id = v_owner and c.kind = 'chore'), '[]'::jsonb),
    'shopping', coalesce((select jsonb_agg(homehq_private.item_json(c) order by c.sort_order, c.id)
      from public.homehq_checklist c where c.owner_id = v_owner and c.kind = 'shopping'), '[]'::jsonb),
    'devices', coalesce((select jsonb_agg(homehq_private.device_json(d) order by d.sort_order, d.id)
      from public.homehq_devices d where d.owner_id = v_owner), '[]'::jsonb),
    'photos', coalesce((select jsonb_agg(jsonb_build_object(
      'id', p.id, 'path', p.path, 'asset', p.asset, 'caption', p.caption, 'place', p.place
    ) || jsonb_strip_nulls(jsonb_build_object('jpeg_path', p.jpeg_path))
      order by p.sort_order, p.id) from public.homehq_photos p where p.owner_id = v_owner), '[]'::jsonb),
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

ALTER TABLE "public"."homehq_photos"
  ADD CONSTRAINT "homehq_photos_jpeg_path_check" CHECK (((jpeg_path IS NULL) OR ((path IS
    NOT NULL) AND (jpeg_path ~ (('^'::text || (owner_id)::text) || '/[0-9a-f]{64}\.jpg$'::text)))));

CREATE POLICY "homehq_photo_insert" ON "storage"."objects"
  FOR INSERT
  TO "authenticated"
  WITH
    CHECK
    (((bucket_id = 'homehq-photos'::text) AND (name ~ (('^'::text || (( SELECT homehq_private.current_home_id() AS current_home_id))::text) || '/[0-9a-f]{64}\.(png|jpg)$'::text))));

CREATE POLICY "homehq_photo_update" ON "storage"."objects"
  FOR UPDATE
  TO "authenticated"
  USING (((bucket_id = 'homehq-photos'::text) AND ((storage.foldername(name))[1] = (( SELECT homehq_private.current_home_id() AS current_home_id))::text)))
  WITH
    CHECK
    (((bucket_id = 'homehq-photos'::text) AND (name ~ (('^'::text || (( SELECT homehq_private.current_home_id() AS current_home_id))::text) || '/[0-9a-f]{64}\.(png|jpg)$'::text))));
