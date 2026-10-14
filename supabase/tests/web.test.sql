-- Web reads may outgrow the native payload while retaining household isolation.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = pg_catalog, public, extensions;
select extensions.no_plan();
insert into auth.users(id,email,aud,role,raw_app_meta_data,raw_user_meta_data) values
 ('c1111111-1111-4111-8111-111111111111','web-owner@example.test','authenticated','authenticated','{}','{}'),
 ('c2222222-2222-4222-8222-222222222222','web-member@example.test','authenticated','authenticated','{}','{}'),
 ('c3333333-3333-4333-8333-333333333333','web-other@example.test','authenticated','authenticated','{}','{}');
set local request.jwt.claims = '{"sub":"c1111111-1111-4111-8111-111111111111","role":"authenticated"}';
set local role authenticated;
select extensions.lives_ok($$select public.homehq_seed_demo()$$,'first browser signup can initialize the normal sample');
select extensions.lives_ok($$select public.homehq_link_member('web-member@example.test','jordan')$$,'owner links a member');
select extensions.ok(not exists(select 1 from jsonb_array_elements(public.homehq_web_snapshot()->'photos') p where p ? 'web_path'), 'legacy photos need no backfill');
update public.homehq_photos set path=owner_id::text||'/'||repeat('a',64)||'.png',
 jpeg_path=owner_id::text||'/'||repeat('b',64)||'.jpg', web_path=owner_id::text||'/'||repeat('c',64)||'.jpg', web_width=1536, web_height=2048;
select extensions.ok((select bool_and(p->>'web_path' like '%.jpg') from jsonb_array_elements(public.homehq_web_snapshot()->'photos') p),'web reads carry the larger rendition');
select extensions.ok((select bool_and((p->>'web_width')::integer=1536 and (p->>'web_height')::integer=2048) from jsonb_array_elements(public.homehq_web_snapshot()->'photos') p),'web receives portrait dimensions');
select extensions.throws_ok($$update public.homehq_photos set web_width=2049$$,'23514',null::text,'web dimensions stay within the normalized image bound');
select extensions.ok(not exists(select 1 from jsonb_array_elements(public.homehq_snapshot()->'photos') p where p ?| array['web_path','web_width','web_height']), 'installed device payload does not grow with a web path');
select extensions.throws_ok($$update public.homehq_photos set web_path=owner_id::text||'/'||repeat('c',64)||'.png'$$,'23514',null::text,'web rendition must be JPEG');
select extensions.throws_ok($$update public.homehq_photos set web_path='c3333333-3333-4333-8333-333333333333/'||repeat('c',64)||'.jpg'$$,'23514',null::text,'web rendition cannot reference another household');
insert into public.homehq_events(owner_id,id,starts_at,ends_at,title) values
 (auth.uid(),'past',now()-interval '2 months',now()-interval '2 months'+interval '1 hour','Past event'),
 (auth.uid(),'future',now()+interval '2 months',now()+interval '2 months'+interval '1 hour','Future event');
select extensions.is((select count(*)::integer from jsonb_array_elements(public.homehq_web_snapshot()->'events') e where e->>'id' in ('past','future')),2,'web calendar retains past and future events');
select extensions.is((select count(*)::integer from jsonb_array_elements(public.homehq_snapshot()->'events') e where e->>'id' in ('past','future')),0,'device keeps its seven-day window');
insert into public.homehq_photos(owner_id,id) values(auth.uid(),'photo21');
select extensions.is(jsonb_array_length(public.homehq_web_snapshot()->'photos'),21,'web accepts more than twenty photos');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'photos'),20,'installed device keeps twenty photos without failing on a growing household');
select extensions.ok(public.homehq_snapshot()->'truncated' ? 'photos','device projection records omitted photos');
insert into public.homehq_events(owner_id,id,starts_at,ends_at,title)
 select auth.uid(),'extra-event-'||n,now()+interval '1 day',now()+interval '1 day 1 hour',repeat('e',100) from generate_series(1,70) n;
select extensions.is(jsonb_array_length(public.homehq_web_snapshot()->'events'),110,'web returns events beyond the old count and date window');
select extensions.ok(jsonb_array_length(public.homehq_snapshot()->'events')<=64 and public.homehq_snapshot()->'truncated' ? 'events','device projects a bounded earliest agenda');
select extensions.ok(octet_length(public.homehq_snapshot()::text)<=32768,'large photo/calendar collections still fit the device allocation');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'chores'),33,'read-only trimming preserves every editable chore');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'shopping'),24,'read-only trimming preserves every editable shopping item');
savepoint heavy_editable_rows;
update public.homehq_checklist set title=repeat('😀',100), note=repeat('😀',160);
select extensions.throws_ok($$select public.homehq_snapshot()$$,'22023','Home HQ snapshot exceeds 32 KiB','nontrimmable UTF-8 write collections fail safely rather than hiding pending-write targets');
rollback to heavy_editable_rows;
insert into public.homehq_checklist(owner_id,kind,id,title,routine)
 select auth.uid(),'chore','extra'||n,repeat('c',100),'morning' from generate_series(1,70) n;
insert into public.homehq_checklist(owner_id,kind,id,title)
 select auth.uid(),'shopping','extra'||n,repeat('s',100) from generate_series(1,70) n;
select extensions.is(jsonb_array_length(public.homehq_web_snapshot()->'chores'),103,'web accepts more than sixty-four chores');
select extensions.is(jsonb_array_length(public.homehq_web_snapshot()->'shopping'),94,'web accepts more than sixty-four shopping items');
select extensions.ok(octet_length(public.homehq_web_snapshot()::text)>32768,'web can read a household larger than the device HTTP allocation');
select extensions.throws_ok($$select public.homehq_snapshot()$$,'22023','Home HQ display row limit exceeded','oversized write collections preserve installed-client pending actions through explicit refusal');
set local request.jwt.claims = '{"sub":"c2222222-2222-4222-8222-222222222222","role":"authenticated"}';
select extensions.is((select owner_id::text from public.homehq_homes),'c1111111-1111-4111-8111-111111111111','restored member login finds its home without rerunning the bounded seed RPC');
select extensions.is(jsonb_array_length(public.homehq_web_snapshot()->'photos'),21,'member receives the full shared web collection');
select extensions.lives_ok($$insert into storage.objects(bucket_id,name) values('homehq-photos','c1111111-1111-4111-8111-111111111111/'||repeat('c',64)||'.jpg')$$,'member can upload a web JPEG using existing household storage policy');
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),1,'member can read the private web JPEG');
set local request.jwt.claims = '{"sub":"c3333333-3333-4333-8333-333333333333","role":"authenticated"}';
select extensions.throws_ok($$select public.homehq_web_snapshot()$$,'PT404','Initialize Home HQ first','unrelated account cannot read the household web RPC');
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),0,'unrelated account cannot read web JPEG');
select extensions.throws_ok($$insert into storage.objects(bucket_id,name) values('homehq-photos','c1111111-1111-4111-8111-111111111111/'||repeat('d',64)||'.jpg')$$,'42501',null::text,'unrelated account cannot write a household web JPEG');
set local role anon;
select extensions.throws_ok($$select public.homehq_web_snapshot()$$,'42501','permission denied for function homehq_web_snapshot','publishable key alone cannot read household web data');
select extensions.finish();
rollback;
