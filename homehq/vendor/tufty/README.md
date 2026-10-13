# Tufty build dependencies

These are the 17 generic source, font, certificate and attribution files used by
the Home HQ badge builder. They are copied unchanged from
[meech-ward/select-badge](https://github.com/meech-ward/select-badge); the exact
source revision and SHA-256 hashes are in [provenance.json](provenance.json).
Their original paths are preserved below this directory.

The files provide the shared UI/keyboard, cooperative WebSocket transport,
Realtime protocol, reconnect policy, verified TLS, public GTS certificates and
the Mona Sans font. They include no fleet application, account, device
configuration, private state or compiled bytecode. Mona Sans's OFL notice and
the patched aiohttp package's upstream provenance are retained beside their
assets/source.

In the SELECT source repository, `homehq/tools/build.py` reads the canonical
paths. In this standalone fork, it falls back to this directory. Host tests use
the same resolution rule. Edit Home HQ application code under
`homehq/badge/homehq/`; make shared dependency changes in their source repository,
then refresh this explicit allowlist and its provenance together.

The pinned MicroPython compiler and compatible Badgeware firmware are external
toolchain/runtime dependencies, not vendored binaries. See
[BUILD.md](../../BUILD.md) for their exact versions and commands.
