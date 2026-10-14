-- Rollback-only proof of the additive photo variant, including the same
-- membership/Storage authorization used by ordinary browser uploads.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = pg_catalog, public, extensions;
select extensions.no_plan();
insert into auth.users(id,email,aud,role,raw_app_meta_data,raw_user_meta_data) values
 ('b1111111-1111-4111-8111-111111111111','jpeg-owner@example.test','authenticated','authenticated','{}','{}'),
 ('b2222222-2222-4222-8222-222222222222','jpeg-member@example.test','authenticated','authenticated','{}','{}'),
 ('b3333333-3333-4333-8333-333333333333','jpeg-other@example.test','authenticated','authenticated','{}','{}');
set local request.jwt.claims = '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}';
set local role authenticated;
select extensions.lives_ok($$select public.homehq_seed_demo()$$,'owner initializes the existing sample');
select extensions.lives_ok($$select public.homehq_link_member('jpeg-member@example.test','jordan')$$,'owner links a normal household member');
select extensions.ok(not exists(select 1 from jsonb_array_elements(public.homehq_snapshot()->'photos') p
 where p ? 'jpeg_path'), 'legacy/sample photos omit the unused optional JPEG field');
update public.homehq_photos set path=owner_id::text||'/'||repeat('a',64)||'.png',
 jpeg_path=owner_id::text||'/'||repeat('b',64)||'.jpg';
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'photos'),20,'all 20 photos fit with both variants');
select extensions.ok(octet_length(public.homehq_snapshot()::text)<=32768,'full seeded home with 20 JPEG variants remains in the wire budget');
select extensions.ok((select bool_and(p->>'path' like '%.png' and p->>'jpeg_path' like '%.jpg')
 from jsonb_array_elements(public.homehq_snapshot()->'photos') p),'snapshot carries separate correctly labelled PNG/JPEG paths');
select extensions.throws_ok($$update public.homehq_photos set jpeg_path=owner_id::text||'/'||repeat('c',64)||'.png'$$,
 '23514',null::text,'JPEG variant rejects a PNG extension');
select extensions.throws_ok($$update public.homehq_photos set jpeg_path='b3333333-3333-4333-8333-333333333333/'||repeat('c',64)||'.jpg'$$,
 '23514',null::text,'JPEG variant cannot point outside its household');
select extensions.throws_ok($$update public.homehq_photos set path=null$$,
 '23514',null::text,'JPEG variant requires a PNG fallback for existing clients');
set local request.jwt.claims = '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}';
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'photos'),20,'member sees the same photo variants');
select extensions.lives_ok($$insert into storage.objects(bucket_id,name)
 values('homehq-photos','b1111111-1111-4111-8111-111111111111/'||repeat('b',64)||'.jpg')$$,
 'member can upload a content-addressed JPEG in the household folder');
select extensions.lives_ok($$update storage.objects set metadata='{"mimetype":"image/jpeg"}'::jsonb
 where bucket_id='homehq-photos' and name like '%.jpg'$$,'member can replace JPEG bytes through the required UPDATE policy');
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),1,
 'member can select the JPEG for authenticated download/upsert');
select extensions.throws_ok($$insert into storage.objects(bucket_id,name)
 values('homehq-photos','b2222222-2222-4222-8222-222222222222/'||repeat('c',64)||'.jpg')$$,
 '42501',null::text,'member cannot upload to a competing personal folder');
select extensions.throws_ok($$insert into storage.objects(bucket_id,name)
 values('homehq-photos','b1111111-1111-4111-8111-111111111111/not-a-hash.jpg')$$,
 '42501',null::text,'JPEG uploads still require a content hash');
set local request.jwt.claims = '{"sub":"b3333333-3333-4333-8333-333333333333","role":"authenticated"}';
select extensions.is((select count(*)::integer from public.homehq_photos),0,'unrelated user cannot see photo descriptors');
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),0,'unrelated user cannot download the JPEG');
set local role anon;
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),0,'publishable key alone cannot download the JPEG');
select extensions.finish();
rollback;
