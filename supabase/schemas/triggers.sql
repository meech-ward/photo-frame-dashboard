create schema homehq_private;
revoke all on schema homehq_private from public, anon, authenticated;

create function homehq_private.validate_home() returns trigger
language plpgsql security invoker set search_path = '' as $$
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
$$;
revoke all on function homehq_private.validate_home() from public, anon, authenticated;
create trigger homehq_validate_home before insert or update of title, timezone, demo
  on public.homehq_homes for each row execute function homehq_private.validate_home();

create function homehq_private.stamp_checklist_actor() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  -- Direct companion table edits and badge RPCs share this seam. Client-sent
  -- actor UUIDs are overwritten, and retries/metadata edits cannot steal credit.
  if tg_op = 'INSERT' then
    new.created_by_user_id := auth.uid();
    new.completed_by_user_id := case when new.done then auth.uid() else null end;
  else
    -- Auth deletion's FK SET NULL runs without an end-user JWT. RLS already
    -- denies userless client edits; permit this trusted referential cleanup.
    if auth.uid() is null then return new; end if;
    new.created_by_user_id := old.created_by_user_id;
    new.completed_by_user_id := case when not new.done then null
      when not old.done then auth.uid() else old.completed_by_user_id end;
  end if;
  return new;
end;
$$;
revoke all on function homehq_private.stamp_checklist_actor() from public, anon, authenticated;
create trigger homehq_checklist_actor before insert or update on public.homehq_checklist
  for each row execute function homehq_private.stamp_checklist_actor();

create function homehq_private.bump_version() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  -- The server owns versions even when the companion edits a row directly.
  -- Replays never reach this trigger: the RPC returns matching state first.
  new.version := old.version + 1;
  return new;
end;
$$;
revoke all on function homehq_private.bump_version() from public, anon, authenticated;
create trigger homehq_checklist_version before update on public.homehq_checklist
  for each row execute function homehq_private.bump_version();
create trigger homehq_device_version before update on public.homehq_devices
  for each row execute function homehq_private.bump_version();

create function homehq_private.broadcast_change() returns trigger
language plpgsql security definer set search_path = '' as $$
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
$$;
revoke all on function homehq_private.broadcast_change() from public, anon, authenticated;

create trigger homehq_changed after insert or update of title, timezone, demo or delete
  on public.homehq_homes for each row execute function homehq_private.broadcast_change('home');
create trigger homehq_changed after insert or update or delete on public.homehq_people
  for each row execute function homehq_private.broadcast_change('people');
create trigger homehq_changed after insert or update or delete on public.homehq_members
  for each row execute function homehq_private.broadcast_change('people');
create trigger homehq_changed after insert or update or delete on public.homehq_events
  for each row execute function homehq_private.broadcast_change('events');
create trigger homehq_changed after insert or update or delete on public.homehq_event_people
  for each row execute function homehq_private.broadcast_change('events');
create trigger homehq_changed after insert or update or delete on public.homehq_checklist
  for each row execute function homehq_private.broadcast_change('checklist');
create trigger homehq_changed after insert or update or delete on public.homehq_cards
  for each row execute function homehq_private.broadcast_change('cards');
create trigger homehq_changed after insert or update or delete on public.homehq_devices
  for each row execute function homehq_private.broadcast_change('devices');
create trigger homehq_changed after insert or update or delete on public.homehq_photos
  for each row execute function homehq_private.broadcast_change('photos');
