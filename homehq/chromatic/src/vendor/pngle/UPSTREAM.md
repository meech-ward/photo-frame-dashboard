# Streaming PNG dependency

Upstream: [kikuchan/pngle](https://github.com/kikuchan/pngle), version 1.1.0,
commit `b1c68193f1d3f8642b3e0e095d457a828038e6fb` (2025-05-18).
`pngle.h`, `miniz.c`, `miniz.h` and `LICENSE` are unmodified files downloaded
from that commit. `pngle.c` has one documented local correction below.
Pngle is MIT licensed; miniz's public-domain
dedication is retained at the end of its source.

| File | SHA-256 |
| --- | --- |
| pngle.c (upstream) | cfd047df6464ac299ecd47aeb13fecfb55f1d841da56dc57085248ef43655049 |
| pngle.c (local unsigned-shift correction) | 513fdbe0ecca52aae96725ca4741c096839c6ed7e50215023ac233ce8c927304 |
| pngle.h | d8aa264f80cdd884c02ca1e28b696e8bbfbc16074c9c5265fcec4463f563bb17 |
| miniz.c | 97efe2132abc8346a3d11f29f84b574f5da78a1b94432ea42b0c754c7c39da4e |
| miniz.h | 8a638511f9f98e8240fc00522989fe7908a06f73a6386191e4374046c993cfa0 |
| LICENSE | f965b67dece0b41367e5b66ba8b6787a93381e61d81121dbb5d87f6b2f330b39 |

The local correction casts the four bytes in `read_uint32` to `uint32_t`
before shifting. The bundled coast image's CRC triggered signed left-shift
overflow in the original routine under UBSan. The corrected mailbox test passes
ASan and UBSan with `UBSAN_OPTIONS=halt_on_error=1`. The decoding behavior stays
the same; parsing is defined for the full range of PNG lengths and CRCs.

Reproduce from the repository root:

```sh
python3 -m unittest discover -s homehq/chromatic/tests -p 'test_photo*.py'
HQ_PHOTO_SANITIZE=1 UBSAN_OPTIONS=halt_on_error=1 python3 homehq/chromatic/tests/test_photo_mailbox.py
```

Compile `pngle.c` and `miniz.c` once each. `miniz.h` includes the declaration
section of `miniz.c`; it is intentionally a 52-byte upstream file. Gamma tables
are never requested. `PNGLE_NO_GAMMA_CORRECTION` can remove their optional code.

The Home HQ wrapper validates the fixed 320x240, 8-bit RGB/indexed/RGBA,
non-interlaced contract before passing IHDR to Pngle. Network fragments are
bounded to 2 KiB, every PNG chunk CRC is checked by Pngle, and the complete
76,800 source-pixel count is required before publication. Source pixels are
sampled into a 96x72 RGB565 picture centred inside a 128x72 image. The decoder
holds a 32 KiB Deflate window, its approximately 11 KiB inflater, and a bounded
scanline; it never retains a full source image or the compressed download.

## Repository whitespace normalization

Upstream CRLF/trailing whitespace was normalized to LF for the mandatory Git
whitespace gate, without changing C tokens or line numbering. Final local hashes:

- `miniz.c`: `43dd50906f3ebd0ba12ad2e8aa3e2709fe07525cf79ce56e4c0ab829601d12b3` (before normalization `97efe2132abc8346a3d11f29f84b574f5da78a1b94432ea42b0c754c7c39da4e`).
