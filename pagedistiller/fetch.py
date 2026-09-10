"""Plain HTTP GET of a URL -- the first, cheapest rung of the extraction chain.

Serves the common case: a normal static or server-rendered page. No browser, no
rendering. The response body is size-capped while streaming so a hostile or very
large page can not blow up memory, and the request carries a normal browser-like
User-Agent so the destination treats us like ordinary traffic.

The only network call PageDistiller makes is to the destination site itself; this
module is where that call happens.
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 20.0
DEFAULT_CHUNK_SIZE = 64 * 1024
DEFAULT_MAX_BYTES = 32 * 1024 * 1024

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)

# Rung that produced a fetch-served page; the rendering step records its own
# ("lightpanda" / "chromium") before handing back to distill.
FETCH_METHOD = "fetch"


class FetchError(Exception):
    """A plain-fetch attempt failed (timeout, connection, HTTP, oversize)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    client: httpx.Client | None = None,
) -> httpx.Response:
    """GET ``url`` and return the response, following redirects.

    The body is read in a streaming, size-capped fashion: more than ``max_bytes``
    is truncated to exactly ``max_bytes`` and the remainder of the stream is
    discarded without being held in memory. A browser-like User-Agent is sent so
    the destination treats the request as ordinary page traffic.

    ``client`` is an injection seam: pass an :class:`httpx.Client` (e.g. one
    backed by ``httpx.MockTransport``) to make the fetch deterministic and
    offline. When omitted, a real client is built and closed here.
    """
    own_client = client is None
    http = client if client is not None else httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        return _get_capped(
            http,
            url,
            timeout=timeout,
            max_bytes=max_bytes,
            headers={"User-Agent": _USER_AGENT},
        )
    finally:
        if own_client:
            http.close()


def _get_capped(
    http: httpx.Client,
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    headers: dict,
) -> httpx.Response:
    """Stream, cap by size, and rebuild a complete :class:`httpx.Response`.

     A non-2xx status raises :class:`FetchError` (an HTTP failure is not a
    rendered page). A transport-level failure likewise surfaces as
     :class:`FetchError` rather than an httpx exception leaking the public API.

     The ``headers`` are applied per-request so they reach a caller-supplied
    client too, not only the self-built one.

     The reassembled body is already decoded -- httpx decodes the stream as it is
    read -- so the ``content-encoding`` it carried on the wire (e.g. ``gzip``) is
    dropped from the rebuilt headers, and ``content-length`` is dropped too since
    it described the compressed length, which a size cap may have truncated.
    Leaving either in would make a later ``.content`` / ``.text`` access try to
    decompress already-decoded bytes, exploding with a ``zlib`` error on any
    compressed page -- which is every modern site over HTTPS.
      """
    try:
        with http.stream("GET", url, timeout=timeout, headers=headers) as response:
            response.raise_for_status()
            content = _read_capped(response, max_bytes)
            rebuilt = _cleaned_headers(response.headers)
            return httpx.Response(
                status_code=response.status_code,
                headers=rebuilt,
                content=content,
                request=response.request,
                extensions=response.extensions,
                history=response.history or None,
               )
    except httpx.HTTPStatusError as exc:
        raise FetchError(
            f"HTTP {exc.response.status_code} for {exc.request.url}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.TransportError as exc:
        raise FetchError(f"could not reach {url}: {exc}") from exc


def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    """Stream the body into at most ``max_bytes``.

    ``httpx`` does not populate ``content`` for a streamed request, so we read
    chunk by chunk and stop accumulating once the cap is hit. An over-sized chunk
    is truncated to what fits, then the iterator keeps draining so the remaining
    body is read off the socket and the connection can be released -- we never
    hold the tail in memory. The per-request timeout set on the client governs
    this loop; the body stream itself takes no timeout.
    """
    buffer = bytearray()
    total = 0
    for chunk in response.iter_bytes():
        remaining = max_bytes - total
        if remaining <= 0:
            continue
        keep = chunk[:remaining]
        buffer += keep
        total += len(keep)
    return bytes(buffer)


# Headers that described the on-wire (compressed, untruncated) body and would
# mislead a consumer of the rebuilt decoded body if left untouched. ``httpx``
# keys its headers by lowercased ASCII names, so the set uses the same str form.
_DROP_ON_REBUILD = frozenset({"content-encoding", "content-length", "transfer-encoding"})


def _cleaned_headers(headers: httpx.Headers) -> httpx.Headers:
    kept = [
         (name, value)
        for name, value in headers.multi_items()
        if name not in _DROP_ON_REBUILD
      ]
    return httpx.Headers(kept)
