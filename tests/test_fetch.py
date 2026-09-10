"""fetch(): plain HTTP GET via httpx, with a MockTransport for offline tests.

No test hits the real network -- every response comes from an in-process
``httpx.MockTransport``.
"""

import httpx
import pytest

from pagedistiller.fetch import (
    FetchError,
    _USER_AGENT,
    fetch,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler),
                        follow_redirects=True)


def test_fetch_returns_html_body():
    def handler(request):
        return httpx.Response(200, request=request,
                              content=b"<html><body>hi</body></html>",
                              headers={"content-type": "text/html"})

    result = fetch("http://example.com", client=_client(handler))
    assert result.status_code == 200
    assert result.text == "<html><body>hi</body></html>"
    assert str(result.url) == "http://example.com"


def test_fetch_sends_browser_user_agent():
    seen = {}
    def handler(request):
        seen["user-agent"] = request.headers.get("user-agent")
        return httpx.Response(200, request=request, content=b"ok")

    fetch("http://example.com", client=_client(handler))
    assert "Mozilla" in seen["user-agent"]
    assert seen["user-agent"] == _USER_AGENT


def test_fetch_follows_redirects():
    def handler(request):
        if str(request.url) == "http://example.com/start":
            return httpx.Response(302, request=request,
                                  headers={"location": "http://example.com/finish"})
        return httpx.Response(200, request=request, content=b"final")

    result = fetch("http://example.com/start", client=_client(handler))
    assert str(result.url) == "http://example.com/finish"
    assert len(result.history) == 1


def test_fetch_http_error_raises_fetch_error():
    def handler(request):
        return httpx.Response(404, request=request, content=b"not found")

    with pytest.raises(FetchError):
        fetch("http://example.com/missing", client=_client(handler))


def test_fetch_http_error_carries_status_code():
    def handler(request):
        return httpx.Response(503, request=request, content=b"service unavailable")

    with pytest.raises(FetchError) as exc_info:
        fetch("http://example.com/blocked", client=_client(handler))
    assert exc_info.value.status_code == 503


def test_fetch_transport_error_has_no_status_code():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(FetchError) as exc_info:
        fetch("http://example.com", client=_client(handler))
    assert exc_info.value.status_code is None


def test_fetch_caps_body_size():
    big = b"A" * 100_000
    def handler(request):
        return httpx.Response(200, request=request, content=big,
                              headers={"content-length": str(len(big))})

    result = fetch("http://example.com/big", max_bytes=1024,
                   client=_client(handler))
    assert len(result.content) == 1024
    assert result.content == b"A" * 1024


def test_fetch_truncates_oversized_single_chunk():
    big = b"X" * 5000
    def handler(request):
        return httpx.Response(200, request=request, content=big)

    result = fetch("http://example.com/big", max_bytes=500,
                   client=_client(handler))
    assert len(result.content) == 500


def test_fetch_decodes_gzip_without_redecode_error():
    """A gzip-encoded body must come back decoded once, not twice.

    Regression: the rebuilt response used to keep ``content-encoding: gzip``
    over already-decoded bytes, so a later ``.text`` access tried a second
    decompress and raised ``zlib.error`` -- which is every modern page over
    HTTPS. The raw body here is a real gzip payload httpx decodes on the wire.
    """
    import gzip

    body = gzip.compress(b"<html><body>compressed page body</body></html>")

    def handler(request):
        return httpx.Response(
            200,
            request=request,
            content=body,
            headers={"content-encoding": "gzip"},
        )

    result = fetch("http://example.com/gzip", client=_client(handler))
        # No exception on this access is the point; the body is decoded text.
    assert "content-encoding" not in {k.lower() for k in result.headers}
    assert result.text == "<html><body>compressed page body</body></html>"
    assert result.content == b"<html><body>compressed page body</body></html>"
