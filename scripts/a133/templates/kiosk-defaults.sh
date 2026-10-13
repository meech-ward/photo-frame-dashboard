# Kiosk defaults re-applied every boot (paste into /system/bin/phh-on-boot.sh). user_rotation 3 matches
# ro.surface_flinger.primary_display_orientation=ORIENTATION_270 on this panel; verify yours with Pointer location.
settings put system accelerometer_rotation 0
settings put system user_rotation 3
settings put secure charging_sounds_enabled 0      # the "boot chime" is the charging sound
settings put global power_sounds_enabled 0
settings put system lockscreen_sounds_enabled 0
settings put system dtmf_tone 0
[ "$(settings get system screen_brightness_mode)" = "1" ] || settings put system screen_brightness_mode 1
