ALTER TABLE "public"."homehq_members"
  DROP CONSTRAINT "homehq_members_owner_id_person_id_fkey";

ALTER TABLE "public"."homehq_members"
  ADD CONSTRAINT "homehq_members_owner_id_person_id_fkey" FOREIGN KEY (owner_id, person_id) REFERENCES public.homehq_people(owner_id, id);
