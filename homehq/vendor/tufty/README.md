# Tufty build dependencies

These are the 17 generic source, font, certificate and attribution files used by
the Home HQ badge builder. Start at [badge.select/guides](https://badge.select/guides)
for SELECT setup and its current source links.

The 16 runtime and asset files match the public
[SELECT source](https://github.com/supabase-community/select-2026-badge/tree/ff92a8484419942f18039bace5663da1c53061b6)
byte for byte. [provenance.json](provenance.json) records that revision, each
public source path and every SHA-256 hash. The remaining file is Home HQ's
aiohttp attribution note, whose separate public origin is also recorded there.
The local directory names are retained so existing build imports stay stable.

The files provide the shared UI/keyboard, cooperative WebSocket transport,
Realtime protocol, reconnect policy, verified TLS, public GTS certificates and
the Mona Sans font. They include no fleet application, account, device
configuration, private state or compiled bytecode. Mona Sans's OFL notice and
the patched aiohttp package's upstream provenance are retained beside their
assets/source.

The standalone builder and host tests read this directory. Edit Home HQ application code under
`homehq/badge/homehq/`; make shared dependency changes in their source repository,
then refresh this explicit allowlist and its provenance together.

The pinned MicroPython compiler and compatible Badgeware firmware are external
toolchain/runtime dependencies, not vendored binaries. See
[BUILD.md](../../BUILD.md) for their exact versions and commands.
