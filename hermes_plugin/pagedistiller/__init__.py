"""PageDistiller web-extract plugin for Hermes.

A thin adapter -- all extraction logic lives in the standalone
``pagedistiller`` package (a separate install into the hermes venv; see
PLAN.md section 6). Registers extract-only, so it never competes with the
configured search backend (e.g. ``ddgs``).

Deploy this directory (as-is) to ``~/.hermes/plugins/web/pagedistiller/``.
"""

from __future__ import annotations

from .provider import PageDistillerWebSearchProvider


def register(ctx) -> None:
    """Plugin entry point -- called once at load time."""
    ctx.register_web_search_provider(PageDistillerWebSearchProvider())
