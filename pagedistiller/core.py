"""Orchestration: fetch a URL, distill it, and escalate to browser rendering when
the plain fetch comes back too thin, or looks like a bot-challenge wall, to be
the real page.

The common case is one cheap HTTP GET followed by a trafilatura distill. When
that yields little or nothing -- or the page is a Cloudflare/bot-challenge
interstitial rather than real content -- a real browser has to render it. Those
renderers land in the rendering step (:mod:`pagedistiller.render`, default
engine: nodriver); this module wires them in through a single ``renderer`` seam
so the orchestration is complete now and the heavy dependency is layered on
without changing the call shape.

``Result.method`` records the rung that actually produced the returned content
(``"fetch"``, or a renderer's name such as ``"nodriver"``) -- useful for
debugging and a first-class field in the tests, not an afterthought.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Tuple

from . import distill as _distill
from . import fetch as _fetch

FETCH_METHOD = _fetch.FETCH_METHOD

# A distilled body shorter than this is treated as "thin" -- not the real page, but
# a JS shell or near-empty scrape worth escalating to a renderer. A real article
# body runs into thousands of characters; a shell yields a handful. This mirrors
# hermes's own rule of thumb (a near-empty distill means JS was needed),
# generalized from its ~20-char browser-snapshot cutoff to distilled prose. The
# exact value is a PLAN open question, tunable and overridable per call, decided
# from real results rather than hardcoded here.
MIN_CONTENT_CHARS = 100

# A renderer attempts JS/browser rendering of ``url`` in priority order and
# yields one ``(method, rendered_html)`` pair per attempt -- e.g. nodriver --
# or yields nothing when no renderer can serve it. ``extract`` feeds each result
# back through the distill step and keeps the first that is not thin.
Renderer = Callable[[str], Iterable[Tuple[str, str]]]


@dataclass(frozen=True)
class Result:
    """The distilled view of one URL.

    ``method`` is the rung that produced ``content`` -- ``"fetch"`` on the common
    path, or a renderer's name (e.g. ``"nodriver"``) on escalation.
    ``error`` is a diagnostic string when nothing usable came back; it is ``None``
    when ``content`` is usable (even if thin-but-non-empty).
    """

    url: str
    title: str
    content: str
    method: str
    error: Optional[str] = None


def is_thin(content: str, threshold: int = MIN_CONTENT_CHARS) -> bool:
    """True when ``content`` is too short to be the real page body.

    The rule of thumb: a near-empty distill means the page needed JS to render.
    ``content`` is stripped first so whitespace padding can not disguise emptiness.
    """
    return len(content.strip()) < threshold


def is_challenge(title: str, content: str) -> bool:
    """True when title or content indicates a bot challenge or verification wall."""
    t = title.lower()
    if "just a moment" in t or "attention required" in t:
        return True
    c = content.lower()
    if "cf-browser-verification" in c or "turnstile" in c:
        return True
    if "checking your browser before accessing" in c:
        return True
    return False


def extract(url: str, *, renderer: Optional[Renderer] = None,
            min_content_chars: int = MIN_CONTENT_CHARS, **fetch_kwargs) -> Result:
    """Distill ``url`` into a :class:`Result`.

    Fetches the page over plain HTTP, distills it, and -- when the result is thin
    or a challenge page -- escalates to ``renderer`` (a browser rendering chain).
    Without a renderer the function still returns honestly: whatever content
    the plain fetch produced, with no disguised success. ``**fetch_kwargs``
    forward to :func:`pagedistiller.fetch.fetch` (e.g. ``timeout``, ``max_bytes``,
    or a ``client`` for offline testing).
    """
    final_url = url
    try:
        response = _fetch.fetch(url, **fetch_kwargs)
        final_url = str(response.url)
        fetched = _distill.distill(response.text, final_url)
    except _fetch.FetchError as exc:
        # A challenge response (HTTP 403 / 503) can be rescued by the browser renderer;
        # connection or 404 errors stay honest fetch failures.
        if renderer is not None and getattr(exc, "status_code", None) in (403, 503):
            escalated = _escalate(renderer, final_url, min_content_chars)
            if escalated is not None:
                return escalated
        return Result(url=url, title="", content="",
                     method=FETCH_METHOD, error=str(exc))

    if not is_thin(fetched.content, min_content_chars) and not is_challenge(fetched.title, fetched.content):
        return Result(final_url, fetched.title, fetched.content, FETCH_METHOD)

    # Thin or challenge: escalate to the rendering chain, if one is wired in.
    if renderer is not None:
        escalated = _escalate(renderer, final_url, min_content_chars)
        if escalated is not None:
            return escalated

    # No renderer, or every rendering attempt stayed thin: return the best plain
    # result rather than claiming a fallback we did not actually take.
    return Result(final_url, fetched.title, fetched.content, FETCH_METHOD,
                  error=_thin_error(fetched.content))


def _escalate(renderer: Renderer, url: str, threshold: int) -> Optional[Result]:
    """Run the renderer chain and return the first attempt that is not thin."""
    for method, rendered_html in renderer(url):
        rendered = _distill.distill(rendered_html, url)
        if not is_thin(rendered.content, threshold):
            return Result(rendered.url or url, rendered.title,
                         rendered.content, method)
    return None


def _thin_error(content: str) -> Optional[str]:
    """A diagnostic when a thin-but-non-empty page is all we have, else None."""
    if content.strip():
        return None
    return "no content -- page likely needs JS rendering (no renderer available)"
