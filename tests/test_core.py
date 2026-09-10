"""core(): orchestration -- fetch, distill, and thin-result escalation.

The fetch step is served by an in-process ``httpx.MockTransport``; the distill
step is the real trafilatura run on that HTML; the renderer step is a fake that
yields HTML, so the escalation path is exercised end to end without a real
browser.
"""

import httpx
import pytest

from pagedistiller import core
from pagedistiller.core import Result, extract, is_challenge, is_thin


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _good_body() -> bytes:
    return (
         b"<html><head><title>Good Page</title></head><body>"
         b"<nav>Home About Contact</nav>"
         b"<article><h1>Real</h1>"
         b"<p>This is a real article body with plenty of sentences so the content "
         b"is not considered thin and the plain fetch is enough for this page.</p></article>"
         b"<footer>copyright 2026</footer></body></html>"
     )


def _thin_shell() -> bytes:
    return b"<html><head><title>Loader</title></head><body><div id='root'></div></body></html>"


def _rendered_body() -> str:
    return (
         "<html><head><title>Rendered</title></head><body>"
         "<article><h1>After JS</h1>"
         "<p>This is the rendered body that is only present after JavaScript runs, "
         "with several sentences so it is not thin and the renderer result is kept.</p>"
         "</article></body></html>"
     )


# --- is_thin heuristic -------------------------------------------------------

def test_is_thin_short_is_thin():
    assert is_thin("") is True
    assert is_thin("just a snippet") is True
    assert is_thin("    ") is True
    assert is_thin("x" * 50, threshold=100) is True


def test_is_thin_long_is_not_thin():
    assert is_thin("x" * 300, threshold=100) is False
    assert is_thin("this is a real body paragraph" * 10) is False


def test_is_thin_respects_custom_threshold():
    assert is_thin("short", threshold=6) is True
    assert is_thin("shorter", threshold=6) is False


# --- is_challenge heuristic ---------------------------------------------------

def test_is_challenge_detects_title_markers():
    assert is_challenge("Just a moment...", "") is True
    assert is_challenge("Attention Required! | Cloudflare", "") is True
    assert is_challenge("just a MOMENT", "") is True  # case-insensitive


def test_is_challenge_detects_content_markers():
    assert is_challenge("", "please wait, cf-browser-verification is running") is True
    assert is_challenge("", "complete the Turnstile challenge below") is True
    assert is_challenge("", "Checking your browser before accessing example.com") is True


def test_is_challenge_false_for_normal_page():
    assert is_challenge("Real Article", "a normal article body about gardening") is False
    assert is_challenge("", "") is False


# --- the common path ---------------------------------------------------------

def test_extract_common_path_returns_fetch():
    def handler(request):
        return httpx.Response(200, request=request, content=_good_body())
    result = extract("http://example.com", client=_client(handler))
    assert isinstance(result, Result)
    assert result.method == core.FETCH_METHOD
    assert result.method == "fetch"
    assert "real article body" in result.content
    assert result.error is None
    assert "Home About Contact" not in result.content


# --- thin-result escalation --------------------------------------------------

def test_extract_escalates_to_renderer_when_thin():
    def handler(request):
        return httpx.Response(200, request=request, content=_thin_shell())
    def renderer(url):
        yield ("lightpanda", _rendered_body())
    result = extract("http://example.com", renderer=renderer,
                     client=_client(handler))
    assert result.method == "lightpanda"
    assert "rendered body that is only present after JavaScript" in result.content
    assert result.error is None


def test_extract_escalation_walks_renderer_chain():
    seen = []
    def renderer(url):
        seen.append("lightpanda")
        yield ("lightpanda", _thin_shell())
        seen.append("chromium")
        yield ("chromium", _rendered_body())
    def handler(request):
        return httpx.Response(200, request=request, content=_thin_shell())
    result = extract("http://example.com", renderer=renderer,
                     client=_client(handler))
    assert result.method == "chromium"
    assert seen == ["lightpanda", "chromium"]
    assert "rendered body" in result.content


def test_extract_renderer_all_thin_returns_fetch():
    def renderer(url):
        yield ("lightpanda", _thin_shell())
        yield ("chromium", _thin_shell())
    def handler(request):
        return httpx.Response(200, request=request, content=_thin_shell())
    result = extract("http://example.com", renderer=renderer,
                     client=_client(handler))
    assert result.method == "fetch"
    assert result.content == ""
    assert result.error is not None


def test_extract_no_renderer_thin_returns_error():
    def handler(request):
        return httpx.Response(200, request=request, content=_thin_shell())
    result = extract("http://example.com", client=_client(handler))
    assert result.method == "fetch"
    assert result.content == ""
    assert result.error is not None
    assert "rendering" in result.error.lower()


def test_extract_fetch_failure_reported_not_rescued():
    def renderer(url):
        raise AssertionError("renderer must not run when fetch failed")
    def handler(request):
        raise httpx.ConnectError("boom")
    result = extract("http://unreachable.example", renderer=renderer,
                     client=_client(handler))
    assert result.method == "fetch"
    assert result.content == ""
    assert result.error is not None


# --- 403/503 challenge escalation ---------------------------------------------

def test_extract_403_escalates_to_renderer():
    def handler(request):
        return httpx.Response(403, request=request, content=b"blocked")
    def renderer(url):
        yield ("nodriver", _rendered_body())
    result = extract("http://example.com", renderer=renderer, client=_client(handler))
    assert result.method == "nodriver"
    assert "rendered body" in result.content
    assert result.error is None


def test_extract_503_escalates_to_renderer():
    def handler(request):
        return httpx.Response(503, request=request, content=b"service unavailable")
    def renderer(url):
        yield ("nodriver", _rendered_body())
    result = extract("http://example.com", renderer=renderer, client=_client(handler))
    assert result.method == "nodriver"
    assert result.error is None


def test_extract_403_no_renderer_stays_honest():
    def handler(request):
        return httpx.Response(403, request=request, content=b"blocked")
    result = extract("http://example.com", client=_client(handler))
    assert result.method == "fetch"
    assert result.content == ""
    assert result.error is not None


def test_extract_404_is_not_escalated():
    # Only a challenge-shaped status (403/503) is worth a renderer retry; a
    # plain 404 is not something a browser can rescue.
    def handler(request):
        return httpx.Response(404, request=request, content=b"not found")
    def renderer(url):
        raise AssertionError("renderer must not run for a plain 404")
    result = extract("http://example.com", renderer=renderer, client=_client(handler))
    assert result.method == "fetch"
    assert result.error is not None


def test_extract_min_content_chars_override():
    def renderer(url):
        raise AssertionError("renderer must not run: content beats the low threshold")
    def handler(request):
        return httpx.Response(200, request=request, content=_good_body())
    result = extract("http://example.com", min_content_chars=1, renderer=renderer,
                     client=_client(handler))
    assert result.method == "fetch"
    assert "real article body" in result.content
