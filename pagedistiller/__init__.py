"""PageDistiller: fetch a URL and distill it to clean, boilerplate-free content.

Public API:
    from pagedistiller import extract, Result
    result = extract("https://example.com")
    if result.content:
        print(result.title, result.content)

``Result.method`` names the rung that served the page: ``"fetch"`` (plain
HTTP GET, the common case), or a browser-rendering fallback (``"nodriver"`` by
default) wired in by the rendering step.

Enabling the fallback is a one-liner -- ``extract(url, renderer=default_renderer())`` --
which runs nodriver (Chromium over CDP) when the plain fetch comes back too thin
or looks like a bot-challenge page. ``default_renderer`` is a function (not a
pre-built object) so importing ``pagedistiller`` stays cheap and pulls in the
rendering engine only when asked.
"""

from __future__ import annotations

from .core import Result, extract
from .render import default_renderer

__all__ = ["extract", "Result", "default_renderer"]
