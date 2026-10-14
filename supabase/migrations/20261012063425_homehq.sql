REVOKE ALL ON TABLE "public"."homehq_cards" FROM "authenticated";

GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE "public"."homehq_cards" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_checklist" FROM "authenticated";

GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE "public"."homehq_checklist" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_devices" FROM "authenticated";

GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE "public"."homehq_devices" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_event_people" FROM "authenticated";

GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE "public"."homehq_event_people" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_events" FROM "authenticated";

GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE "public"."homehq_events" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_homes" FROM "authenticated";

REVOKE ALL ("demo") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("demo"), UPDATE ("demo") ON TABLE "public"."homehq_homes" TO "authenticated";

REVOKE ALL ("owner_id") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("owner_id") ON TABLE "public"."homehq_homes" TO "authenticated";

REVOKE ALL ("timezone") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("timezone"), UPDATE ("timezone") ON TABLE "public"."homehq_homes" TO "authenticated";

REVOKE ALL ("title") ON TABLE "public"."homehq_homes" FROM "authenticated";

GRANT INSERT ("title"), UPDATE ("title") ON TABLE "public"."homehq_homes" TO "authenticated";

GRANT DELETE, SELECT ON TABLE "public"."homehq_homes" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_people" FROM "authenticated";

GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE "public"."homehq_people" TO "authenticated";

REVOKE ALL ON TABLE "public"."homehq_photos" FROM "authenticated";

GRANT DELETE, INSERT, SELECT, UPDATE ON TABLE "public"."homehq_photos" TO "authenticated";
