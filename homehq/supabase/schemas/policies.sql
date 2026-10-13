-- Explicit privileges are intentional: current Supabase projects do not always
-- auto-expose new objects, and the publishable key alone authorizes no home data.
alter table public.homehq_homes enable row level security;
alter table public.homehq_members enable row level security;
alter table public.homehq_people enable row level security;
alter table public.homehq_events enable row level security;
alter table public.homehq_event_people enable row level security;
alter table public.homehq_checklist enable row level security;
alter table public.homehq_cards enable row level security;
alter table public.homehq_devices enable row level security;
alter table public.homehq_photos enable row level security;

create policy homehq_member_read on public.homehq_members for select to authenticated
  using (owner_id = (select homehq_private.current_home_id()));
create policy homehq_home_read on public.homehq_homes for select to authenticated
  using (owner_id = (select homehq_private.current_home_id()));
create policy homehq_home_create on public.homehq_homes for insert to authenticated
  with check (owner_id = (select auth.uid()) and owner_id = (select homehq_private.current_home_id()));
create policy homehq_home_edit on public.homehq_homes for update to authenticated
  using (owner_id = (select homehq_private.current_home_id()))
  with check (owner_id = (select homehq_private.current_home_id()));
create policy homehq_home_delete on public.homehq_homes for delete to authenticated
  using (owner_id = (select auth.uid()));
create policy homehq_household on public.homehq_people for all to authenticated
  using ((select homehq_private.current_home_id()) = owner_id)
  with check ((select homehq_private.current_home_id()) = owner_id);
create policy homehq_household on public.homehq_events for all to authenticated
  using ((select homehq_private.current_home_id()) = owner_id)
  with check ((select homehq_private.current_home_id()) = owner_id);
create policy homehq_household on public.homehq_event_people for all to authenticated
  using ((select homehq_private.current_home_id()) = owner_id)
  with check ((select homehq_private.current_home_id()) = owner_id);
create policy homehq_household on public.homehq_checklist for all to authenticated
  using ((select homehq_private.current_home_id()) = owner_id)
  with check ((select homehq_private.current_home_id()) = owner_id);
create policy homehq_household on public.homehq_cards for all to authenticated
  using ((select homehq_private.current_home_id()) = owner_id)
  with check ((select homehq_private.current_home_id()) = owner_id);
create policy homehq_household on public.homehq_devices for all to authenticated
  using ((select homehq_private.current_home_id()) = owner_id)
  with check ((select homehq_private.current_home_id()) = owner_id);
create policy homehq_household on public.homehq_photos for all to authenticated
  using ((select homehq_private.current_home_id()) = owner_id)
  with check ((select homehq_private.current_home_id()) = owner_id);

-- Supabase may default new public tables to ALL for authenticated. A narrow
-- GRANT does not remove those inherited ACLs: revoke first so RLS cannot be
-- bypassed by TRUNCATE and server-owned home fields stay database-authored.
revoke all on public.homehq_members, public.homehq_homes, public.homehq_people, public.homehq_events,
  public.homehq_event_people, public.homehq_checklist, public.homehq_cards,
  public.homehq_devices, public.homehq_photos from public, anon, authenticated;
grant select, insert, update, delete on public.homehq_people, public.homehq_events,
  public.homehq_event_people, public.homehq_checklist, public.homehq_cards,
  public.homehq_devices, public.homehq_photos to authenticated;
grant select on public.homehq_members to authenticated;
grant select, delete on public.homehq_homes to authenticated;
grant insert (owner_id, title, timezone, demo) on public.homehq_homes to authenticated;
grant update (title, timezone, demo) on public.homehq_homes to authenticated;

-- Only the database publishes. A notification is a hint to fetch durable state,
-- so clients need receive access but no direct Broadcast send policy.
create policy homehq_receive on realtime.messages for select to authenticated
  using (
    extension = 'broadcast'
    and (select auth.uid()) is not null
    and (select realtime.topic()) = 'homehq:' || (select homehq_private.current_home_id())::text
    and topic = 'homehq:' || (select homehq_private.current_home_id())::text
  );

-- Storage stays private. Authenticated downloads use the user's JWT instead of
-- saving an expiring signed URL in a badge's persistent snapshot.
create policy homehq_photo_read on storage.objects for select to authenticated
  using (bucket_id = 'homehq-photos' and (storage.foldername(name))[1] = (select homehq_private.current_home_id())::text);
create policy homehq_photo_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'homehq-photos'
    and name ~ ('^' || (select homehq_private.current_home_id())::text || '/[0-9a-f]{64}\.(png|jpg)$'));
create policy homehq_photo_update on storage.objects for update to authenticated
  using (bucket_id = 'homehq-photos' and (storage.foldername(name))[1] = (select homehq_private.current_home_id())::text)
  with check (bucket_id = 'homehq-photos'
    and name ~ ('^' || (select homehq_private.current_home_id())::text || '/[0-9a-f]{64}\.(png|jpg)$'));
create policy homehq_photo_delete on storage.objects for delete to authenticated
  using (bucket_id = 'homehq-photos' and (storage.foldername(name))[1] = (select homehq_private.current_home_id())::text);
