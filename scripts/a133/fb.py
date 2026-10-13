# Minimal fastboot client (read-only use). Usage: fb.py "getvar:version" ...
import sys, usb.core, usb.util
d = usb.core.find(idVendor=0x1f3a, idProduct=0x1010) or usb.core.find(custom_match=lambda x: any(i.bInterfaceClass==0xff and i.bInterfaceSubClass==0x42 for c in x for i in c))
if not d: sys.exit("no fastboot device")
try: d.set_configuration()
except usb.core.USBError: pass
intf = d.get_active_configuration()[(0,0)]
epo = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)==usb.util.ENDPOINT_OUT)
epi = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)==usb.util.ENDPOINT_IN)
ALLOWED = ("getvar:",)   # safety: refuse anything else
import os
if os.environ.get("FB_ALLOW_REBOOT_FASTBOOT")=="1": ALLOWED += ("reboot-fastboot",)
if os.environ.get("FB_ALLOW_REBOOT")=="1": ALLOWED += ("reboot",)
for cmd in sys.argv[1:]:
    if not cmd.startswith(ALLOWED): print(f"REFUSED (not read-only): {cmd}"); continue
    epo.write(cmd.encode()); out=[]
    while True:
        try: r = bytes(epi.read(512, timeout=5000)).decode(errors="replace")
        except usb.core.USBTimeoutError: out.append("<timeout>"); break
        out.append(r)
        if r[:4] in ("OKAY","FAIL"): break
    print(f"{cmd!r} -> {out}")
