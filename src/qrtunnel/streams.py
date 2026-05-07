"""Small stream utilities used by uploads."""

# ── LimitedStream (Manual Implementation) ────────────────
# Werkzeug 3.0.0 removed LimitedStream. Re-implementing a
# minimal version to ensure upload stability.
class LimitedStream:
    def __init__(self, stream, limit):
        self._stream = stream
        self._limit = limit
        self._pos = 0

    def read(self, size=-1):
        if self._pos >= self._limit:
            return b""
        if size < 0 or size > self._limit - self._pos:
            size = self._limit - self._pos
        data = self._stream.read(size)
        self._pos += len(data)
        return data

    def readline(self, size=-1):
        if self._pos >= self._limit:
            return b""
        if size < 0 or size > self._limit - self._pos:
            size = self._limit - self._pos
        data = self._stream.readline(size)
        self._pos += len(data)
        return data


