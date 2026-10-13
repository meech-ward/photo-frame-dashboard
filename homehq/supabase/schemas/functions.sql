-- These formatters keep the RPC and full snapshot on the exact same row shape.
-- They are invokers in a non-exposed schema and accept no owner lookup inputs.
grant usage on schema homehq_private to authenticated;
create function homehq_private.current_home_id() returns uuid
language sql stable security definer set search_path = '' as $$
  -- This lookup has no caller-supplied identity. Definer access breaks the
  -- membership-policy recursion; every result is still limited to auth.uid().
  select coalesce((select owner_id from public.homehq_members where user_id = auth.uid()), auth.uid());
$$;
revoke all on function homehq_private.current_home_id() from public, anon;
grant execute on function homehq_private.current_home_id() to authenticated;

create function homehq_private.link_member(p_email text, p_person_id text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  v_owner uuid := auth.uid();
  v_user uuid;
  v_email text;
  v_linked uuid;
begin
  -- Only the real home owner can resolve an Auth email or grant membership.
  -- The definer is needed for auth.users lookup; no secret key reaches clients.
  if v_owner is null or not exists (select 1 from public.homehq_homes where owner_id = v_owner)
    or homehq_private.current_home_id() <> v_owner then
    raise exception using errcode = '42501', message = 'Only the household owner can link accounts';
  end if;
  if p_email is null or char_length(trim(p_email)) not between 3 and 254 or p_person_id is null
    or not exists (select 1 from public.homehq_people where owner_id = v_owner and id = p_person_id) then
    raise exception using errcode = '22023', message = 'Choose an email and a person from this household';
  end if;
  select id, email into v_user, v_email from auth.users
    where lower(email) = lower(trim(p_email)) and deleted_at is null and not is_anonymous;
  if not found then raise exception using errcode = 'PT404', message = 'Create that email account first'; end if;
  if v_user <> v_owner and exists (select 1 from public.homehq_homes where owner_id = v_user) then
    raise exception using errcode = '22023', message = 'That account already owns a different household';
  end if;
  if exists (select 1 from public.homehq_members where owner_id = v_owner and person_id = p_person_id and user_id <> v_user) then
    raise exception using errcode = '22023', message = 'That person already has a linked account';
  end if;
  -- The conflict WHERE makes a concurrent second-home link fail atomically,
  -- rather than moving an account after a stale preflight membership check.
  insert into public.homehq_members(user_id, owner_id, person_id) values (v_user, v_owner, p_person_id)
    on conflict (user_id) do update set person_id = excluded.person_id
      where homehq_members.owner_id = excluded.owner_id
    returning user_id into v_linked;
  if v_linked is null then
    raise exception using errcode = '22023', message = 'That account already belongs to another household';
  end if;
  return jsonb_build_object('home_id', v_owner, 'user_id', v_user, 'person_id', p_person_id, 'email', v_email);
end;
$$;
revoke all on function homehq_private.link_member(text, text) from public, anon;
grant execute on function homehq_private.link_member(text, text) to authenticated;

create function public.homehq_link_member(p_email text, p_person_id text) returns jsonb
language sql security invoker set search_path = '' as $$
  select homehq_private.link_member(p_email, p_person_id);
$$;
revoke all on function public.homehq_link_member(text, text) from public, anon;
grant execute on function public.homehq_link_member(text, text) to authenticated;
create function homehq_private.utc_offset_minutes(p_time timestamptz, p_timezone text) returns integer
language sql stable security invoker set search_path = '' as $$
  -- A seven-day agenda can cross a clock change. Using today's home offset for
  -- every event would move next week's local clock time by an hour.
  select extract(epoch from ((p_time at time zone p_timezone) - (p_time at time zone 'UTC')))::integer / 60;
$$;
revoke all on function homehq_private.utc_offset_minutes(timestamptz, text) from public, anon;
grant execute on function homehq_private.utc_offset_minutes(timestamptz, text) to authenticated;

create function homehq_private.item_json(p_item public.homehq_checklist) returns jsonb
language sql immutable security invoker set search_path = '' as $$
  select case when p_item.kind = 'chore' then jsonb_build_object(
    'id', p_item.id, 'who', coalesce(p_item.person_id, 'any'), 'routine', p_item.routine,
    'title', p_item.title, 'stars', p_item.stars, 'done', p_item.done,
    'done_by', p_item.done_by, 'version', p_item.version,
    'created_by_user_id', p_item.created_by_user_id, 'completed_by_user_id', p_item.completed_by_user_id
  ) else jsonb_build_object(
    'id', p_item.id, 'name', p_item.title, 'category', p_item.category,
    'store', p_item.store, 'quantity', p_item.quantity, 'note', p_item.note,
    'done', p_item.done, 'version', p_item.version,
    'created_by_user_id', p_item.created_by_user_id, 'completed_by_user_id', p_item.completed_by_user_id
  ) end;
$$;
revoke all on function homehq_private.item_json(public.homehq_checklist) from public, anon;
grant execute on function homehq_private.item_json(public.homehq_checklist) to authenticated;

create function homehq_private.device_json(p_device public.homehq_devices) returns jsonb
language sql immutable security invoker set search_path = '' as $$
  select jsonb_strip_nulls(jsonb_build_object(
    'id', p_device.id, 'name', p_device.name, 'room', p_device.room, 'type', p_device.type,
    'on', p_device.on_state, 'level', p_device.level, 'locked', p_device.locked,
    'state', p_device.garage_state, 'version', p_device.version, 'sample', true
  ));
$$;
revoke all on function homehq_private.device_json(public.homehq_devices) from public, anon;
grant execute on function homehq_private.device_json(public.homehq_devices) to authenticated;

create function public.homehq_snapshot() returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
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
$$;
revoke all on function public.homehq_snapshot() from public, anon;
grant execute on function public.homehq_snapshot() to authenticated;

create function public.homehq_set_done(
  p_kind text, p_id text, p_done boolean, p_version bigint, p_done_by text default null
) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
  v_owner uuid := homehq_private.current_home_id();
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
$$;
revoke all on function public.homehq_set_done(text, text, boolean, bigint, text) from public, anon;
grant execute on function public.homehq_set_done(text, text, boolean, bigint, text) to authenticated;

create function public.homehq_set_device(p_id text, p_state jsonb, p_version bigint) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
  v_owner uuid := homehq_private.current_home_id();
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
$$;
revoke all on function public.homehq_set_device(text, jsonb, bigint) from public, anon;
grant execute on function public.homehq_set_device(text, jsonb, bigint) to authenticated;

create function public.homehq_save_event(
  p_id text, p_title text, p_start bigint, p_end bigint, p_people text[],
  p_loc text default '', p_notes text default '', p_travel integer default 0, p_all_day boolean default false
) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
  v_owner uuid := homehq_private.current_home_id();
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
$$;
revoke all on function public.homehq_save_event(text, text, bigint, bigint, text[], text, text, integer, boolean) from public, anon;
grant execute on function public.homehq_save_event(text, text, bigint, bigint, text[], text, text, integer, boolean) to authenticated;
