# Public MCU baseline

`mcu-baseline.patch` applies to the public
[ModRetro MCU source](https://github.com/ModRetro/oss-chromatic-console-mcu)
at [`6c94613da72420f6a364e0024681401bd69184ba`](https://github.com/ModRetro/oss-chromatic-console-mcu/tree/6c94613da72420f6a364e0024681401bd69184ba).
`mcu-baseline.json` pins that revision, every original target-file SHA-256 and
the patch SHA-256. `prepare.py` checks these before applying the patch, then
copies the Home HQ application and performs its measured display/TLS setup.

The patch changes seven files:

- `main/main.c`: run Home HQ on the sole LVGL task, initialize its service and
  console queues first, and leave dashboard updates awake.
- `components/button/button.c` and `.h`: expose held button state because the
  factory consumed-edge API omits Select.
- `main/fpga_tx.c` and `.h`: reopen the factory overlay with a complete synthetic
  menu press/release, preserving the existing FPGA protocol.
- `main/CMakeLists.txt`: declare the Wi-Fi, verified client HTTP/TLS and JSON
  components the app uses.
- `sdkconfig.defaults`: retain the constrained Wi-Fi/socket/LVGL/crypto defaults
  used by the tested Home HQ port; preparation selects client TLS and applies
  the measured dynamic-buffer and display budgets.

No camera, bloom, boot-screen app, local programming guide, private settings,
firmware dump or deployment output is included. A separate unpublished MCU
commit is unnecessary. The remaining dependencies are the documented public
ESP-IDF and LVGL versions; applying this source patch does not flash a device.

This patch modifies ModRetro's GPLv3 source and is distributed under GPL-3.0-only.
The upstream [GNU GPL version 3 license](mcu-baseline-LICENSE) is copied
unchanged. Keep it and the source patch when redistributing this baseline;
the application sources and bundled third-party notices remain alongside it.
