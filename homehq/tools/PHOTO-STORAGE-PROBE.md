# Offline physical photo storage probe

`photo_storage_probe.py` is a USB-fed acceptance probe for the installed Home HQ
bytecode on a Tufty2350 with ABI **7942**. Set `HOMEHQ_PROBE_TARGET` to the
selected device's UID before executing the source. The probe refuses a missing
or mismatched target and other board models. Select the exact connected Tufty
and run through `mpremote` from a fresh raw REPL after verifying its installation.

The probe uses the actual installed `SupabaseTransport.download_photo`, `contain`
and `photo` methods on a no-network object. `FakeHTTP` supplies an in-RAM, exactly
**327680-byte** legal 320×240 8-bit non-interlaced RGB PNG. A 584-byte compressed
image is embedded; a CRC-valid ancillary `tEXt` chunk supplies the remaining
bytes without needing a device zlib module. The fixture never occupies flash,
so it cannot accidentally create the third-photo storage load being measured.

Before any writes, the probe refuses if either real cache slot, either slot's
temporary file, or its reserve file already exists. It does not overwrite,
back up, rename or delete a previously downloaded photo. All other `/state`
files, including credentials and other applications' state, are hashed privately
in RAM and checked before and after. Hashes, tokens, passwords, file contents and
raw exceptions never appear in the output.

The actual existing state is counted. Only when necessary, an owned reserve file
brings other-state bytes to **103 KiB**. Initial free space must allow two capped
photos, that reserve and 32 KiB of metadata headroom. The 16-second hardware
watchdog is fed during hashing, padding, writes and drawing. Real filesystem
writes are instrumented in 4 KiB chunks to sample peak photo bytes, actual
`statvfs` headroom and heap; recorded write timings include instrumentation.

The run proves:

1. Three consecutive maximum-size downloads to slot 0, slot 1, then slot 0 again.
2. An HTTP rejection preserves the old destination before any eviction.
3. A deliberate short write creates 32 KiB of real partial flash data, then the
   installed error path removes its temporary file and releases the active latch.
4. The same photo queues again and a fourth full-size download succeeds.
5. Peak photo file bytes never exceed **655360**; positive minimum flash headroom
   is reported from the actual state volume.
6. The real image decoder and `HomeView` draw the photo on the physical display;
   dimensions and a centre framebuffer pixel are checked, so fallback artwork
   cannot falsely pass.
7. All pre-existing state hashes remain unchanged. Cleanup removes only the
   probe-created two slots, their temporary files and optional reserve.

Safe result records start with `HOMEHQ_PHOTO_PROBE`. A successful `summary`
explicitly labels the network as simulated HTTP. This proves physical flash,
cleanup and PNG decode/draw; it makes **no HTTPS, Wi-Fi, Auth or Realtime claim**.
After an interrupted USB session, inspect only the probe's owned paths before
rerunning; the initial refusal prevents accidental cleanup of unknown files.

After setting `TUFTY_PORT` and `TUFTY_UID` to the selected device, run from the
repository root:

```sh
mpremote connect "$TUFTY_PORT" exec "HOMEHQ_PROBE_TARGET='$TUFTY_UID'" \
  run homehq/tools/photo_storage_probe.py
```

`run` reads the host file and executes its source in RAM. Do **not** copy a padded
PNG fixture to `/state`; use the embedded small PNG and in-RAM construction.

Offline fixture, guard and real-host-filesystem tests can run without USB:

```sh
python3 -B homehq/tools/test_photo_storage_probe.py
```

Those tests validate all PNG CRCs and decompressed pixels, preservation/refusal
guards, three replacements, partial cleanup and retry. A negative control proves
the monitor rejects the previous design that holds two slots plus a temporary
third file. Only running the probe on the selected device can establish a physical pass.
