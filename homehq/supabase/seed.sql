-- Local resets create the private bucket but no shared password or fake session.
-- The companion signs a person in and calls homehq_seed_demo() as that owner.
-- SQL tests use rollback-only Auth fixtures and never seed a production account.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('homehq-photos', 'homehq-photos', false, 2097152, array['image/png', 'image/jpeg'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
