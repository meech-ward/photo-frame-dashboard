-- Browsers need the complete calendar and photo collection. The device RPC
-- narrows this RLS-protected projection to its MicroPython allocation budget.
-- Web photo renditions stay out of that device response.
create function public.homehq_web_snapshot() returns jsonb
language plpgsql stable security invoker set search_path = '' as $$
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
$$;
revoke all on function public.homehq_web_snapshot() from public, anon;
grant execute on function public.homehq_web_snapshot() to authenticated;
