"""
Integration: the rendering fallback path, plus a stable real URL.

Every test is skippable, so the offline suite (``pytest -q``, no network, no
browser) runs the offline cases and skips the network case without error -- the
"marked so they can be skipped offline/in CI" intent of PLAN section 3.

Two things are proven that unit tests can only fake:
* the escalation path runs for real -- a JS shell served by a local HTTP
    server (no network) is thin on plain fetch and is rescued by a real renderer;
* the "no disguised success" contract holds -- with no renderer, that same thin
    shell is returned as a fetch result with an explanatory error, not faked.

The stable-URL case hits the network and is skipped when it is unreachable, or when
the site refuses the plain fetch (an access failure a renderer cannot fix).
"""

import threading

from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest

from pagedistiller import default_renderer, extract
from pagedistiller.render import _chromium_binary, default_engines

pytestmark = pytest.mark.integration

_SHELL_JS = "document.getElementById('root').innerHTML = '<h1>Rendered Headline</h1>' + '<p>' + ('This is the long rendered body that only exists after JS runs. '.repeat(8)) + '</p>';"
_SHELL = b"<html><head><title>App</title></head><body><div id='root'></div><script>" + _SHELL_JS.encode() + b"</script></body></html>"


def _has_browser() -> bool:
    if _chromium_binary() is not None:
        return True
    return any(engine.is_available() for engine in default_engines())


class _ShellHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.send_header("content-length", str(len(_SHELL)))
        self.end_headers()
        self.wfile.write(_SHELL)
    
    def log_message(self, *args) -> None:
        pass


def _serve_one(fn) -> None:
    server = HTTPServer(("127.0.0.1", 0), _ShellHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        fn(f"http://127.0.0.1:{port}/")
    finally:
        thread.join(timeout=5)
        server.shutdown()


@pytest.mark.skipif(not _has_browser(), reason="no render browser available")
def test_forced_fallback_renders_js_shell_offline() -> None:
    """
A JS shell is thin on plain fetch and must escalate to a real renderer.

Runs entirely offline against a local HTTP server; a real renderer fills the
empty shell body, so the kept content came from a renderer rung not the
fetch -- the "end to end, not just in theory" check of PLAN section 3.
"""
    def go(url: str) -> None:
        render = default_renderer(attempt_timeout=30.0, total_deadline=60.0)
        result = extract(url, renderer=render)
        assert result.method in ("nodriver", "lightpanda", "chromium")
        assert "rendered body that only exists after JS runs" in result.content
        assert result.error is None
    
    _serve_one(go)


@pytest.mark.skipif(_has_browser(), reason="a browser is present; the shell renders")
def test_forced_fallback_offline_without_browser_stays_honest() -> None:
    """
With no renderer, the same thin shell is reported, not faked.

The "no disguised success" contract: with no escalation path a thin page is
returned as a ``fetch`` result with an explanatory error, not a pretend render.
"""
    def go(url: str) -> None:
        result = extract(url)
        assert result.method == "fetch"
        assert result.content.strip() == ""
        assert result.error is not None
    
    _serve_one(go)


def test_real_stable_url_is_fetchable_and_thick() -> None:
    """
A stable page is served by the plain fetch and is not thin.

``example.com`` is the canonical stable test page and returns a 200 to a
browser-like request; skipped when it cannot be fetched here (no network).
"""
    result = extract("https://example.com/", min_content_chars=100)
    if result.error is not None:
        pytest.skip(f"example.com not fetchable here: {result.error}")
    assert len(result.content.strip()) >= 100
    assert "documentation examples" in result.content or result.title == "Example Domain"
