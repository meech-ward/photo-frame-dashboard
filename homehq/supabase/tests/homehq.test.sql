-- Rollback-only database behavior proof. This exercises real roles/RLS, not a
-- source-text matcher. A separate HTTP/WebSocket test must prove wire delivery.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = pg_catalog, public, extensions;
select extensions.no_plan();

insert into auth.users(id, email, aud, role, raw_app_meta_data, raw_user_meta_data) values
  ('11111111-1111-4111-8111-111111111111','homehq-one@example.test','authenticated','authenticated','{}','{}'),
  ('22222222-2222-4222-8222-222222222222','homehq-two@example.test','authenticated','authenticated','{}','{}');

select extensions.ok((
  select bool_and(c.relrowsecurity) from pg_catalog.pg_class c
  join pg_catalog.pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relname like 'homehq_%' and c.relkind = 'r'
), 'every Home HQ table has RLS');
select extensions.ok((
  select not bool_or(has_table_privilege('authenticated', c.oid,
    'TRUNCATE, REFERENCES, TRIGGER, MAINTAIN')) from pg_catalog.pg_class c
  join pg_catalog.pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relname like 'homehq_%' and c.relkind = 'r'
), 'authenticated inherits no privileged table operations from Supabase defaults');
select extensions.ok(not has_column_privilege('authenticated','public.homehq_homes','revision','UPDATE')
  and not has_column_privilege('authenticated','public.homehq_homes','updated_at','UPDATE')
  and not has_column_privilege('authenticated','public.homehq_homes','owner_id','UPDATE')
  and not has_column_privilege('authenticated','public.homehq_homes','revision','INSERT'),
  'owner cannot author server-owned home fields');
select extensions.ok((
  select not bool_or(p.prosecdef) from pg_catalog.pg_proc p
  join pg_catalog.pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public' and p.proname like 'homehq_%'
), 'all exposed Home HQ RPCs are security invokers');
select extensions.ok(not has_function_privilege('authenticated', 'homehq_private.broadcast_change()', 'EXECUTE'),
  'the database publisher is unavailable to clients');

set local request.jwt.claims = '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}';
set local role authenticated;
select extensions.lives_ok($$select public.homehq_seed_demo()$$, 'owner one initializes through the invoker RPC');
select extensions.throws_ok($$update public.homehq_homes set revision=999$$,'42501',null::text,
  'normal owner cannot directly replace the server revision');
select extensions.throws_ok($$truncate public.homehq_people cascade$$,'42501',null::text,
  'normal owner cannot truncate rows outside RLS');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'people'), 4, 'the exact four demo people are present');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'events'), 38, 'seven-day sample contains 38 events');
select extensions.ok((select bool_and(event ? 'start_offset_minutes' and event ? 'end_offset_minutes')
  from jsonb_array_elements(public.homehq_snapshot()->'events') event),
  'snapshot carries timezone offsets for both event endpoints');
select extensions.is(homehq_private.utc_offset_minutes('2026-10-31 10:00:00-04'::timestamptz,'America/Toronto'),-240,
  'Toronto offset before the 2026 November clock change is minus four hours');
select extensions.is(homehq_private.utc_offset_minutes('2026-11-01 10:00:00-05'::timestamptz,'America/Toronto'),-300,
  'Toronto November 1 10 AM event uses minus five hours');
select extensions.is((extract(epoch from ('2026-11-01 10:00:00-05'::timestamptz))::bigint
  + homehq_private.utc_offset_minutes('2026-11-01 10:00:00-05'::timestamptz,'America/Toronto')*60) % 86400,
  36000::bigint,'November 1 event endpoint renders at 10 AM using its own offset');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'chores'), 33, 'all 33 source chores are present');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'shopping'), 24, 'all 24 source shopping items are present');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'agents'), 5, 'all five source agent samples are present');
select extensions.ok(octet_length(public.homehq_snapshot()::text) <= 32768, 'complete sample snapshot fits the 32 KiB body cap');
select extensions.is(public.homehq_snapshot()->'home_status'->>'lights_on','3','home summary counts the three sample lights');

select extensions.is(public.homehq_set_done('shopping','g1',true,1)->>'status','saved','first desired value is saved');
select extensions.is((select version from public.homehq_checklist where kind='shopping' and id='g1'),2::bigint,
  'first mutation advances the server-owned item version');
select extensions.is(public.homehq_set_done('shopping','g1',true,1)->>'status','saved','lost-response replay converges despite its old version');
select extensions.is((select version from public.homehq_checklist where kind='shopping' and id='g1'),2::bigint,
  'converged replay does not increment the version');
select extensions.is(public.homehq_set_done('shopping','g1',false,1)->>'status','conflict','contradictory stale client loses the version race');
select extensions.ok((select done from public.homehq_checklist where kind='shopping' and id='g1'),
  'conflicting request does not overwrite the winner');
select extensions.is(public.homehq_set_done('shopping','g1',false,2)->>'status','saved','fresh version can undo the item');
select extensions.is(public.homehq_set_done('shopping','g1',true,2)->>'status','conflict','the previous winner cannot reapply after another client changed the row');

select extensions.throws_ok($$select public.homehq_set_done('chore','c21',true,1)$$,'22023',
  'Choose the person completing this chore','an any-person chore requires attribution');
select extensions.is(public.homehq_set_done('chore','c21',true,1,'maya')->'item'->>'done_by','maya',
  'an any-person chore records the chosen household person');
select extensions.is(public.homehq_set_done('chore','c21',true,1,'maya')->>'status','saved','chore retry converges without a second award');
select extensions.throws_ok($$select public.homehq_set_done('chore','c6',true,1,'alex')$$,'22023',
  'Choose the person completing this chore','an assigned chore cannot be credited to someone else');

select extensions.is(public.homehq_set_device('kitchen-light','{"on":false}',1)->>'status','saved','sample light updates through the desired-state RPC');
select extensions.is(public.homehq_snapshot()->'home_status'->>'lights_on','2','snapshot summary reflects the device mutation');
select extensions.is(public.homehq_set_device('kitchen-light','{"on":false}',1)->>'status','saved','sample device replay is converged success');
select extensions.is(public.homehq_set_device('kitchen-light','{"on":true}',1)->>'status','conflict','stale contradictory device state is refused');
select extensions.throws_ok($$select public.homehq_set_device('front-door','{"on":true}',1)$$,'22023',
  'State is invalid for this sample device','lock refuses light-only state keys');
select extensions.throws_ok($$select public.homehq_set_device('kitchen-light','{"level":101}',2)$$,'22023',
  'Light level must be an integer from 0 to 100','light level has a bounded integer range');
select extensions.throws_ok($$select public.homehq_set_device('kitchen-light','{"level":"bad"}',2)$$,'22023',
  'Light level must be an integer from 0 to 100','invalid JSON value has a controlled validation error');

select extensions.lives_ok($$select public.homehq_save_event('test-event','Test event',1791747900,1791750600,array['alex','otto'])$$,
  'calendar save atomically creates the event and attendees');
select extensions.is((select count(*)::integer from public.homehq_event_people where event_id='test-event'),2,
  'both selected attendees were stored');
select extensions.throws_ok($$select public.homehq_save_event('test-event','Broken update',1791747900,1791750600,array['missing'])$$,
  '22023','Choose people from this home','invalid attendee refuses the complete event edit');
select extensions.is((select title from public.homehq_events where id='test-event'),'Test event','failed event edit preserves its previous title');
select extensions.is((select count(*)::integer from public.homehq_event_people where event_id='test-event'),2,
  'failed event edit preserves its previous attendees');

select extensions.lives_ok($$select public.homehq_seed_demo()$$,'ordinary initialize leaves an existing home alone');
select extensions.ok(not (select done from public.homehq_checklist where kind='shopping' and id='g1'),
  'ordinary initialize preserves the user undo');
select extensions.throws_ok($$update public.homehq_homes set timezone='Invalid/Nowhere'$$,'22023','Unknown home timezone',
  'invalid timezone is refused before it can break every snapshot');

set local role postgres;
set local request.jwt.claims = '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}';
set local role authenticated;
select extensions.lives_ok($$select public.homehq_seed_demo()$$, 'owner two can initialize an independent sample');
update public.homehq_people set name='Second owner' where id='alex';
select extensions.is((select name from public.homehq_people where id='alex'),'Second owner','owner sees their own people');
select extensions.is((select count(*)::integer from public.homehq_people where owner_id='11111111-1111-4111-8111-111111111111'),0,
  'cross-owner SELECT returns no rows');
with changed as (
  update public.homehq_people set name='Cross-owner write' where owner_id='11111111-1111-4111-8111-111111111111' returning id
)
select extensions.is((select count(*)::integer from changed),0,'cross-owner UPDATE cannot change a row');
select extensions.throws_ok($$insert into public.homehq_people(owner_id,id,name,color)
  values('11111111-1111-4111-8111-111111111111','outsider','Outsider','#111111')$$,'42501',null::text,
  'cross-owner INSERT is denied');
select extensions.throws_ok($$update public.homehq_people set owner_id='11111111-1111-4111-8111-111111111111' where id='alex'$$,
  '42501',null::text,'WITH CHECK prevents reassigning a row to another owner');

-- Exercise the actual SELECT policy over real rollback-only message rows.
-- SQL role proof is deliberately separate from a successful private WS join.
set local role postgres;
select realtime.send('{"section":"test","revision":1}','changed','homehq:11111111-1111-4111-8111-111111111111',true);
select realtime.send('{"section":"test","revision":1}','changed','homehq:22222222-2222-4222-8222-222222222222',true);
set local realtime.topic = 'homehq:22222222-2222-4222-8222-222222222222';
set local role authenticated;
select extensions.ok(exists(select 1 from realtime.messages where topic='homehq:22222222-2222-4222-8222-222222222222'),
  'owner can read Broadcast rows on their private topic');
select extensions.is((select count(*)::integer from realtime.messages where topic='homehq:11111111-1111-4111-8111-111111111111'),0,
  'owner cannot read another home private topic');
set local realtime.topic = 'homehq:11111111-1111-4111-8111-111111111111';
select extensions.is((select count(*)::integer from realtime.messages),0,'attempted cross-owner join context receives no rows');
select extensions.throws_ok($$insert into realtime.messages(topic,extension,payload,event,private)
  values('homehq:22222222-2222-4222-8222-222222222222','broadcast','{}','changed',true)$$,'42501',null::text,
  'authenticated clients cannot publish their own notifications');

set local role postgres;
insert into storage.objects(bucket_id,name) values
  ('homehq-photos','11111111-1111-4111-8111-111111111111/'||repeat('1',64)||'.png'),
  ('homehq-photos','22222222-2222-4222-8222-222222222222/'||repeat('2',64)||'.png');
set local role authenticated;
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),1,
  'private photos SELECT reveals only the owner folder');
select extensions.throws_ok($$insert into storage.objects(bucket_id,name)
  values('homehq-photos','11111111-1111-4111-8111-111111111111/'||repeat('3',64)||'.png')$$,'42501',null::text,
  'private photos INSERT cannot write another owner folder');
select extensions.throws_ok($$update storage.objects set name='11111111-1111-4111-8111-111111111111/'||repeat('4',64)||'.png'
  where bucket_id='homehq-photos'$$,'42501',null::text,'photo replacement cannot move an object to another owner');

set local role postgres;
set local request.jwt.claims = '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}';
set local role authenticated;
select extensions.is((select name from public.homehq_people where id='alex'),'Wes','owner two did not alter owner one');
insert into public.homehq_checklist(kind,id,title)
  select 'shopping','cap-'||i,'Extra item' from generate_series(1,41) i;
select extensions.throws_ok($$select public.homehq_snapshot()$$,'22023','Home HQ display row limit exceeded',
  '65 shopping rows fail explicitly instead of silently disappearing');
delete from public.homehq_checklist where id like 'cap-%';
update public.homehq_cards set data=jsonb_build_object('sample',true,'summary',repeat('x',7400)) where section='weather';
update public.homehq_cards set data=jsonb_build_object('sample',true,'detail',repeat('x',7400)) where section='home_status';
select extensions.throws_ok($$select public.homehq_snapshot()$$,'22023','Home HQ snapshot exceeds 32 KiB',
  'oversized bounded-card combination still refuses a body above 32 KiB');
select extensions.lives_ok($$select public.homehq_seed_demo(true)$$,'explicit reset restores the complete bounded sample');
select extensions.is((select version from public.homehq_checklist where kind='shopping' and id='g1'),4::bigint,
  'demo reset carries the shopping version forward instead of restarting it');
select extensions.is(public.homehq_set_done('shopping','g1',true,3)->>'status','conflict',
  'queued command from before reset cannot modify the replacement row');
select extensions.is((select version from public.homehq_devices where id='kitchen-light'),3::bigint,
  'demo reset carries the device version forward too');
select extensions.is(public.homehq_set_device('kitchen-light','{"level":20}',2)->>'status','conflict',
  'queued device command from before reset cannot modify the replacement row');

set local role postgres;
set local request.jwt.claims = '{}';
set local role anon;
select extensions.throws_ok($$select * from public.homehq_people$$,'42501',null::text,'publishable-key anonymous role cannot read private people');
select extensions.throws_ok($$select public.homehq_snapshot()$$,'42501',null::text,'anonymous caller cannot execute snapshot');
select extensions.throws_ok($$select public.homehq_seed_demo()$$,'42501',null::text,'anonymous caller cannot initialize a home');
select extensions.is((select count(*)::integer from realtime.messages),0,'anonymous role cannot read private Broadcasts');
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),0,
  'anonymous role cannot read private photos');
set local role postgres;
set local role authenticated;
select extensions.throws_ok($$select public.homehq_snapshot()$$,'42501','Sign in to Home HQ','authenticated role without a user subject is denied');

set local role postgres;
select * from extensions.finish();
rollback;
