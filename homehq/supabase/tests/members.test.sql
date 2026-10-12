-- Real-role proof for one family and four Auth identities. Roll back every row.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = pg_catalog, public, extensions;
select extensions.no_plan();
insert into auth.users(id,email,aud,role,is_anonymous) values
 ('a1111111-1111-4111-8111-111111111111','family-owner@example.test','authenticated','authenticated',false),
 ('a2222222-2222-4222-8222-222222222222','family-two@example.test','authenticated','authenticated',false),
 ('a3333333-3333-4333-8333-333333333333','family-three@example.test','authenticated','authenticated',false),
 ('a4444444-4444-4444-8444-444444444444','family-four@example.test','authenticated','authenticated',false),
 ('a5555555-5555-4555-8555-555555555555','family-outsider@example.test','authenticated','authenticated',false),
 ('a6666666-6666-4666-8666-666666666666','family-linked-only@example.test','authenticated','authenticated',false);
set local request.jwt.claims = '{"sub":"a1111111-1111-4111-8111-111111111111","role":"authenticated"}';
set local role authenticated;
select extensions.lives_ok($$select public.homehq_seed_demo()$$,'owner initializes existing sample contract');
select extensions.is(public.homehq_snapshot()->'viewer'->>'is_owner','true','owner identity is database-derived');
select extensions.lives_ok($$select public.homehq_link_member(' FAMILY-OWNER@example.test ','alex')$$,'owner can link their own account');
select extensions.lives_ok($$select public.homehq_link_member('family-two@example.test','jordan')$$,'owner links second ordinary Auth account');
select extensions.lives_ok($$select public.homehq_link_member('family-three@example.test','maya')$$,'owner links third ordinary Auth account');
select extensions.lives_ok($$select public.homehq_link_member('family-four@example.test','otto')$$,'owner links fourth ordinary Auth account');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'members'),4,'snapshot contains all four mappings');
select extensions.is(public.homehq_snapshot()->'viewer'->>'person_id','alex','owner linked person resolves');
select extensions.throws_ok($$select public.homehq_link_member('family-four@example.test','maya')$$,'22023',
 'That person already has a linked account','linking cannot steal an occupied person');
select extensions.throws_ok($$select public.homehq_link_member('absent@example.test','alex')$$,'PT404',
 'Create that email account first','missing account requires ordinary signup');

set local request.jwt.claims = '{"sub":"a2222222-2222-4222-8222-222222222222","role":"authenticated"}';
select extensions.is(public.homehq_seed_demo()->'home'->>'id','a1111111-1111-4111-8111-111111111111',
 'member initialization returns the shared home without seeding another');
select extensions.is(public.homehq_snapshot()->'viewer'->>'person_id','jordan','second account maps to second person');
select extensions.is(public.homehq_snapshot()->'viewer'->>'is_owner','false','member is not owner');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'members'),4,'member can resolve family attribution names');
select extensions.throws_ok($$select public.homehq_seed_demo(true)$$,'42501',
 'Only the household owner can reset sample data','member cannot reset family data');
select extensions.throws_ok($$select public.homehq_link_member('family-outsider@example.test','alex')$$,'42501',
 'Only the household owner can link accounts','member cannot resolve emails or grant membership');
select extensions.throws_ok($$insert into public.homehq_members(user_id,owner_id,person_id)
 values('a5555555-5555-4555-8555-555555555555','a1111111-1111-4111-8111-111111111111','alex')$$,'42501',null::text,
 'member cannot write the membership table directly');
with removed as (delete from public.homehq_homes returning owner_id)
select extensions.is((select count(*)::integer from removed),0,
 'member cannot delete the shared household');

insert into public.homehq_checklist(owner_id,kind,id,title,person_id,routine,created_by_user_id,completed_by_user_id)
 values('a1111111-1111-4111-8111-111111111111','chore','member-task','Shared task','alex','after',
 'a1111111-1111-4111-8111-111111111111','a1111111-1111-4111-8111-111111111111');
select extensions.is((select created_by_user_id::text from public.homehq_checklist where id='member-task'),
 'a2222222-2222-4222-8222-222222222222','database stamps creator instead of supplied actor');
select extensions.ok((select completed_by_user_id is null from public.homehq_checklist where id='member-task'),
 'unfinished insertion cannot spoof a completion actor');
select extensions.is(public.homehq_set_done('chore','member-task',true,1,'alex')->'item'->>'completed_by_user_id',
 'a2222222-2222-4222-8222-222222222222','completion records the signed-in account separately from assignee credit');
select extensions.is((select person_id from public.homehq_checklist where id='member-task'),'alex','assignment is preserved');

set local request.jwt.claims = '{"sub":"a3333333-3333-4333-8333-333333333333","role":"authenticated"}';
select extensions.is(public.homehq_set_done('chore','member-task',true,1,'alex')->>'status','saved','already matching replay still converges');
select extensions.is((select completed_by_user_id::text from public.homehq_checklist where id='member-task'),
 'a2222222-2222-4222-8222-222222222222','another member replay cannot steal completion');
update public.homehq_checklist set title='Changed title',created_by_user_id='a3333333-3333-4333-8333-333333333333',
 completed_by_user_id='a3333333-3333-4333-8333-333333333333' where id='member-task';
select extensions.is((select created_by_user_id::text from public.homehq_checklist where id='member-task'),
 'a2222222-2222-4222-8222-222222222222','direct metadata write cannot forge original creator');
select extensions.is((select completed_by_user_id::text from public.homehq_checklist where id='member-task'),
 'a2222222-2222-4222-8222-222222222222','direct metadata write cannot forge completion actor');
select extensions.is(public.homehq_set_done('chore','member-task',false,2)->>'status','conflict','stale cross-member undo remains a conflict');
select extensions.is(public.homehq_set_done('chore','member-task',false,3)->>'status','saved','fresh member undo succeeds');
select extensions.ok((select completed_by_user_id is null from public.homehq_checklist where id='member-task'),'undo clears completion actor');
update public.homehq_checklist set done=true,done_by='alex',completed_by_user_id='a1111111-1111-4111-8111-111111111111'
 where id='member-task';
select extensions.is((select completed_by_user_id::text from public.homehq_checklist where id='member-task'),
 'a3333333-3333-4333-8333-333333333333','direct completion is also stamped from authenticated identity');

set local role postgres;
select extensions.is((select count(*)::integer from public.homehq_homes where owner_id in
 ('a2222222-2222-4222-8222-222222222222','a3333333-3333-4333-8333-333333333333','a4444444-4444-4444-8444-444444444444')),0,
 'member initialization did not create separate homes');
select realtime.send('{"section":"test","revision":1}','changed','homehq:a1111111-1111-4111-8111-111111111111',true);
insert into storage.objects(bucket_id,name) values
 ('homehq-photos','a1111111-1111-4111-8111-111111111111/'||repeat('a',64)||'.png');
set local realtime.topic = 'homehq:a1111111-1111-4111-8111-111111111111';
set local role authenticated;
select extensions.ok(exists(select 1 from realtime.messages where topic='homehq:a1111111-1111-4111-8111-111111111111'),
 'member can receive the household private Broadcast');
select extensions.ok(exists(select 1 from storage.objects where bucket_id='homehq-photos'),
 'member can read photos in the existing household folder');
select extensions.lives_ok($$insert into storage.objects(bucket_id,name)
 values('homehq-photos','a1111111-1111-4111-8111-111111111111/'||repeat('b',64)||'.png')$$,
 'member can upload a household photo');
select extensions.throws_ok($$insert into storage.objects(bucket_id,name)
 values('homehq-photos','a3333333-3333-4333-8333-333333333333/'||repeat('c',64)||'.png')$$,'42501',null::text,
 'member cannot create a competing personal folder');

set local request.jwt.claims = '{"sub":"a5555555-5555-4555-8555-555555555555","role":"authenticated"}';
select extensions.is((select count(*)::integer from public.homehq_people),0,'unrelated account cannot read family people');
select extensions.is((select count(*)::integer from public.homehq_members),0,'unrelated account cannot enumerate family accounts');
select extensions.is((select count(*)::integer from realtime.messages),0,'unrelated account cannot receive the family topic');
select extensions.is((select count(*)::integer from storage.objects where bucket_id='homehq-photos'),0,'unrelated account cannot read family photos');
select extensions.throws_ok($$insert into public.homehq_checklist(owner_id,kind,id,title)
 values('a1111111-1111-4111-8111-111111111111','shopping','forged','Forbidden')$$,'42501',null::text,
 'unrelated account cannot create a family task');
select extensions.lives_ok($$select public.homehq_seed_demo()$$,'unrelated account can initialize its own home');
select extensions.throws_ok($$select public.homehq_link_member('family-two@example.test','jordan')$$,'22023',
 'That account already belongs to another household','second owner cannot move an existing member');

set local request.jwt.claims = '{"sub":"a1111111-1111-4111-8111-111111111111","role":"authenticated"}';
select extensions.throws_ok($$select public.homehq_link_member('family-outsider@example.test','alex')$$,'22023',
 'That account already owns a different household','link refuses an existing independent home');
select extensions.lives_ok($$select public.homehq_seed_demo(true)$$,'owner explicit demo reset preserves mappings');
select extensions.is(jsonb_array_length(public.homehq_snapshot()->'members'),4,'all four memberships survive explicit reset');
insert into public.homehq_people(owner_id,id,name,color)
 values('a1111111-1111-4111-8111-111111111111','linked-only','Linked only','#123456');
select public.homehq_link_member('family-linked-only@example.test','linked-only');
set local request.jwt.claims = '{"sub":"a3333333-3333-4333-8333-333333333333","role":"authenticated"}';
select extensions.throws_ok($$delete from public.homehq_people where id='linked-only'$$,'23503',null::text,
 'shared person deletion cannot indirectly unlink a member account');
insert into public.homehq_checklist(owner_id,kind,id,title,done)
 values('a1111111-1111-4111-8111-111111111111','shopping','deleted-actor','Account deletion',true);
set local role postgres;
set local request.jwt.claims = '{}';
select extensions.lives_ok($$delete from auth.users where id='a3333333-3333-4333-8333-333333333333'$$,
 'deleting an Auth account can clear actor foreign keys');
select extensions.ok((select created_by_user_id is null and completed_by_user_id is null
 from public.homehq_checklist where owner_id='a1111111-1111-4111-8111-111111111111' and id='deleted-actor'),
 'trusted referential cleanup does not resurrect deleted actor IDs');
select * from extensions.finish();
rollback;
