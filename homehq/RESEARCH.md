# Wes Bos reference audit — 2026-10-12

The reference checkout is [wesbos/photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard/tree/9dd323e7974f1d4cc10935044386101f9c18e6d0),
commit `9dd323e7974f1d4cc10935044386101f9c18e6d0` (2026-10-11).
This audit covers its README, dashboard shell/mock data, all seven view modules,
slideshow/ambient/alert behavior, visual tokens and layout styles, diagnostics,
Android kiosk and build configuration. Device guides establish the Android
hardware context; their rooting procedures are not badge implementation steps.

## Video transcript obtained and read

The [original video](https://www.youtube.com/watch?v=ZLycoUMltNI) currently reports
the title **Jailbreaking a $50 photo frame**, published 2026-10-09, duration 576
seconds. Its English automatic captions were retrieved directly from YouTube
and read in full on 2026-10-12: 261 timed cues, approximately 1,974 spoken words.
The blog uses the longer title [Hacking Cheap Smart Photo Frames into a Family
Dashboard](https://wesbos.com/hacking-smart-photo-frames).

The ordinary web caption URL returned an empty successful response; the page's
transcript endpoint returned `FAILED_PRECONDITION`. YouTube's public Android
player response exposed an English caption URL which returned 71,810 bytes of
timed XML. Raw-caption SHA-256:
`e65e3a0491476a5c67c0cc0b2d43b6baf660627a12d2e2ad42128ddfee59a9ea`.
The full captions and timestamped text remain private temporary research files,
outside this repository and every export. No audio or video was downloaded.

Video findings (paraphrases, under 200 words):

- **00:00–03:06:** Wes repairs his sister's failed Skylight calendar using its
  Android/debug access and external USB networking; the replacement Wi-Fi
  dongle costs about $11.
- **04:00–07:18:** The inexpensive 10.1-inch frame contains a Rockchip Android
  computer. He replaces its stock software, installs WebView/Chrome 106,
  adjusts swap and uses its motion sensor to dim the display. He keeps Android
  after assessing Linux as impractical for that hardware.
- **07:20–08:30:** His family use case is calendars, chores, reminders,
  shopping lists and photos. He describes a separate agent backend which reads
  school emails, PDFs and Classroom links, adds events/reminders and produces
  spelling-word searches. This is a described existing workflow, not code
  supplied by the published dashboard mock.
- **08:33–09:30:** Frame branding and hardware vary. His shared repository
  records the instructions and research used to take control of the frames.

## Original social post verified

Use [Wes's original X post](https://x.com/wesbos/status/2108550413599265045) for
the later quote-post/repost. X's official public embed metadata confirms author
`wesbos`, post ID `2108550413599265045`, and creation time **2026-10-09
13:29:28 UTC**. It promotes the $50 photo frame, its rooted browser/USB/Wi-Fi
capabilities and 1280×800 touchscreen, linking the video/blog. The exact URL
was located through an indexed reference and independently checked against
X's own `syndication.twitter.com/tweet-result` response. No social action was
taken.

## What the published project actually contains

The [README](https://github.com/wesbos/photo-frame-dashboard/blob/9dd323e7974f1d4cc10935044386101f9c18e6d0/README.md)
identifies the video frame as BIUFRAME/Synergy 10X1, RK3126, Android 6.0.1. Its
dashboard is a Vite web app served by Cloudflare Workers. The small
[Android kiosk](https://github.com/wesbos/photo-frame-dashboard/blob/9dd323e7974f1d4cc10935044386101f9c18e6d0/dashboard/kiosk/src/com/wesbos/homehq/MainActivity.java)
opens that URL in a full-screen WebView; it does not replace the Android OS.
The [data module](https://github.com/wesbos/photo-frame-dashboard/blob/9dd323e7974f1d4cc10935044386101f9c18e6d0/dashboard/js/data.js)
explicitly supplies mock household data. Weather, devices, cameras, media and
agent usage are examples. Sample photographs come from seeded Picsum URLs,
not an exported family photo collection.

The [navigation](https://github.com/wesbos/photo-frame-dashboard/blob/9dd323e7974f1d4cc10935044386101f9c18e6d0/dashboard/index.html)
already has the same seven domains. Native mapping is deliberate:

| Original | Native badge mapping | Deliberate reduction for 320×240/buttons |
| --- | --- | --- |
| Today (`home`) | Clock/date, four-person glance, next event and leave time | Compact family row replaces simultaneous event lanes and side tiles |
| Calendar | Seven-day agenda with all-person colors, dates and event details | No three-day/month grids or badge event typing |
| Chores (`tasks`) | Person/Anyone list, three routines, progress, stars, complete/undo and attribution | One focused lane at a time; no weekly streak grid/reward ledger |
| Shopping | Existing categorized items, quantities, check/undo and stable selection | No badge text entry, usuals/catalog search or quantity editing |
| Photos | Full-frame photo, caption/place, previous/next and play/pause | One cover layout; no collage/polaroid/favourite weighting |
| Home (`control`) | Persistent **sample** lights, lock and garage with explicit confirmation | No real appliance adapter, scenes, blinds, thermostat, camera or music integration |
| Agents | **Sample** plan meters, reset times and activity details | No provider login, live usage collection, billing or pace analysis |

The native port preserves the source's Wes/Claudia/Buzzsaw/Skidmark sample names,
four person colors, cream paper/card/ink palette and amber piano-lesson example.
Mona Sans is the badge's bundled outline font; the source uses Archivo and
Instrument Serif. The port’s bundled landscape illustrations are visibly labelled **SAMPLE ART**.

Ambient/night overlays, alert takeovers, touch gestures and frame motion-sensor
machinery are outside this badge slice. A/C moves domains, UP/DOWN moves focus,
B acts, and A returns from details; explicit lock/garage confirmation replaces
the original hold/slide gestures. The personal Supabase schema, Auth sessions,
private Realtime invalidation, versioned desired values and durable offline
cache are this port's new backend implementation. They are not presented as
Wes's unpublished email-ingestion backend.

## Original browser frontend adopted — 2026-10-12

The owner preferred extending Wes’s repository over a recreated browser UI.
The current display therefore loads his actual seven frontend modules and CSS
at `fbe9a30ac4f9c77d3863e19a5e98d9eadb04ab03`; all 29 original files are
byte-identical and hash checked. The existing editor remains for added account,
member, metadata and upload features. [Source map and limitations](web/UPSTREAM.md).
A real GitHub fork is [meech-ward/photo-frame-dashboard](https://github.com/meech-ward/photo-frame-dashboard).
The native badge stays on its already-tested MicroPython implementation.
