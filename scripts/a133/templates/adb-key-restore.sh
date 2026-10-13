# Re-authorize your computer's ADB key at boot (survives a /data wipe). Paste into /system/bin/phh-on-data.sh.
# Put the contents of YOUR ~/.android/adbkey.pub between the quotes. Tip: strip the trailing "user@host" comment first
# (the key works without it) so your username/hostname don't end up in the image.
K='<contents of ~/.android/adbkey.pub, comment removed>'; F=/data/misc/adb/adb_keys; mkdir -p ${F%/*}
grep -qF "$K" $F || echo "$K" >> $F; chown system:shell $F; chmod 640 $F; restorecon $F
