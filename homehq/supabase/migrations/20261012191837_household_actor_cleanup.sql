SET local check_function_bodies = off;

CREATE OR REPLACE FUNCTION homehq_private.stamp_checklist_actor()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  SET search_path TO ''
  AS $function$
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
$function$;

CREATE INDEX homehq_checklist_completer ON public.homehq_checklist USING btree (completed_by_user_id);

CREATE INDEX homehq_checklist_creator ON public.homehq_checklist USING btree (created_by_user_id);
