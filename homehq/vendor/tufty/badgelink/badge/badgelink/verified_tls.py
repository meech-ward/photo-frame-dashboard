"""Fail-closed TLS adapter for Badgeware v3.0.1's frozen ``fetch`` module.

Stock ``fetch.AsyncFetch._connect`` constructs ``fetch.tls.SSLContext`` and then
assigns ``fetch.tls.CERT_NONE``.  Replacing that one module attribute with this
adapter makes the same assignment mean ``CERT_REQUIRED`` and preloads each DER
root separately.  Repeated ``load_verify_locations`` calls are deliberate:
concatenated DER is not a multi-certificate bundle on this firmware.
"""


_IO_NONE = "none"
_IO_WAIT = "wait"
_IO_PROGRESS = "progress"


def _close_quietly(sock):
    try:
        sock.close()
    except BaseException:
        # Cleanup must preserve the original wrap/handshake exception, including
        # CancelledError and KeyboardInterrupt, which are not Exception subclasses.
        pass


class _TrackedTLSSocket:
    """Socket facade exposing whether the frozen fetch worker did useful I/O."""

    __slots__ = ("_socket", "_raw_socket", "_io", "_closed")

    def __init__(self, tls_socket, raw_socket):
        self._socket = tls_socket
        # PROVENANCE: Pimoroni MicroPython
        # b29530abbd0550c8ab6963024aef36f3cd6cd278,
        # extmod/modtls_mbedtls.c:220-257 detaches sslsock->sock before raising.
        # A second Python owner is therefore required until the first TLS write
        # succeeds; otherwise captive-portal failures leak raw lwIP PCBs until GC.
        self._raw_socket = raw_socket
        self._io = _IO_NONE
        self._closed = False

    def reset_io(self):
        # These interned literals and this pre-existing field make every parked
        # fetch update observable without allocating in the rendered-frame path.
        self._io = _IO_NONE

    def io_state(self):
        return self._io

    def write(self, data):
        try:
            result = self._socket.write(data)
        except BaseException:
            # The pinned port has already discarded its raw reference on fatal
            # handshake errors, so this retained owner is the only deterministic
            # close path.  BaseException also covers cancellation during the call.
            raw_socket = self._raw_socket
            self._raw_socket = None
            if raw_socket is not None:
                _close_quietly(raw_socket)
            raise
        if result is None or result <= 0:
            self._io = _IO_WAIT
        else:
            self._io = _IO_PROGRESS
            # Keep the Python reference even after the deferred handshake has
            # succeeded. Native TLS is still the sole NORMAL close owner, but
            # modtls delegates close through the raw socket's ioctl and that
            # call can itself raise. Without the retained reference an abort in
            # headers/body has no fallback and strands the lwIP PCB.
        return result

    def readline(self):
        result = self._socket.readline()
        # A zero-length result is EOF, not a would-block wait, and lets the
        # caller reach its terminal state in this same frame budget.
        self._io = _IO_WAIT if result is None else _IO_PROGRESS
        return result

    def readinto(self, buffer, length=None):
        # Frozen fetch.py:405/408 passes both readinto(buffer, want) and
        # readinto(buffer).  A fixed optional argument avoids a fresh *args tuple
        # on every body-read update in the rendered-frame path.
        if length is None:
            result = self._socket.readinto(buffer)
        else:
            result = self._socket.readinto(buffer, length)
        # readinto(0) is definitive EOF; only None means the socket would block.
        self._io = _IO_WAIT if result is None else _IO_PROGRESS
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        raw_socket = self._raw_socket
        self._raw_socket = None
        try:
            # On an ordinary pre-handshake abort the native TLS close delegates
            # to raw.  Closing both would double-release the same lwIP socket.
            self._socket.close()
        except BaseException:
            # If delegation itself failed, the still-retained owner is the only
            # remaining deterministic cleanup route; preserve the close error.
            if raw_socket is not None:
                _close_quietly(raw_socket)
            raise


class _TrackedTLSContext:
    __slots__ = ("_context",)

    def __init__(self, context):
        self._context = context

    @property
    def verify_mode(self):
        return self._context.verify_mode

    @verify_mode.setter
    def verify_mode(self, value):
        self._context.verify_mode = value

    def wrap_socket(self, raw_socket, **kwargs):
        # PROVENANCE: Tufty2350 4e268bd8580a690b0f0b0976bd69d06a73e4e512,
        # modules/common/fetch.py:232-246 wraps before publishing self._sock.
        try:
            tls_socket = self._context.wrap_socket(raw_socket, **kwargs)
        except BaseException:
            # Frozen fetch still owns no writer at this point, so its outer
            # cleanup cannot reach raw if wrapping is cancelled or raises.
            _close_quietly(raw_socket)
            raise
        return _TrackedTLSSocket(tls_socket, raw_socket)


class VerifiedTLSShim:
    def __init__(self, tls_module, ca_paths, track_io=False):
        paths = tuple(ca_paths)
        if not paths:
            raise ValueError("at least one DER CA path is required")
        if any(not isinstance(path, str) or not path for path in paths):
            raise ValueError("DER CA paths must be non-empty strings")
        self._tls = tls_module
        self._ca_paths = paths
        self._track_io = bool(track_io)
        self.PROTOCOL_TLS_CLIENT = tls_module.PROTOCOL_TLS_CLIENT
        # This is the stock fetch.py seam: its request for CERT_NONE is mapped
        # to CERT_REQUIRED.  There is intentionally no unverified mode here.
        self.CERT_NONE = tls_module.CERT_REQUIRED
        self.CERT_REQUIRED = tls_module.CERT_REQUIRED

    @property
    def ca_paths(self):
        return self._ca_paths

    def SSLContext(self, protocol):
        context = self._tls.SSLContext(protocol)
        context.verify_mode = self._tls.CERT_REQUIRED
        for path in self._ca_paths:
            context.load_verify_locations(cafile=path)
        # Flag-OFF keeps the production object graph exactly as before; the
        # wrapper exists only in the cold-built non-blocking-connect artifact.
        if not self._track_io:
            return context
        return _TrackedTLSContext(context)


def install(fetch_module, tls_module, ca_paths, track_io=False):
    """Install a verified adapter and return the previous ``fetch.tls`` value."""

    previous = fetch_module.tls
    fetch_module.tls = VerifiedTLSShim(
        tls_module, ca_paths, track_io=track_io
    )
    return previous


def restore(fetch_module, previous):
    """Restore the exact prior ``fetch.tls`` object after a finite probe."""

    fetch_module.tls = previous
