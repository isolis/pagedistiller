"""PageDistiller extract-only provider for Hermes.

All fetch/distill/render logic lives in the standalone ``pagedistiller``
package -- this file only adapts its ``Result`` to the shape
``agent.web_search_provider.WebSearchProvider`` expects. Nothing here calls
the network or a browser directly; it's a thin translation layer, as PLAN.md
asks for.

Extract-only: ``supports_search`` stays ``False`` (the ABC default is
``True``, so it must be overridden), so this provider never competes with, or
silently replaces, whatever search backend (e.g. ``ddgs``) is configured.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.web_search_provider import WebSearchProvider


class PageDistillerWebSearchProvider(WebSearchProvider):
    """Local fetch + distill (with a nodriver render fallback)."""

    def __init__(self) -> None:
        self._renderer = None  # built once, lazily -- see _get_renderer

    @property
    def name(self) -> str:
        return "pagedistiller"

    @property
    def display_name(self) -> str:
        return "PageDistiller"

    def is_available(self) -> bool:
        """Cheap import check only -- no network, per the ABC's contract."""
        try:
            import pagedistiller  # noqa: F401
        except ImportError:
            return False
        return True

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Extract each URL via ``pagedistiller.core.extract`` -- no extraction
        logic duplicated here. Unknown ``kwargs`` (``format``, ``include_raw``,
        ``max_chars``) are ignored per the ABC's contract; PageDistiller always
        returns clean text.
        """
        import pagedistiller

        renderer = self._get_renderer()
        return [
            self._to_entry(pagedistiller.extract(url, renderer=renderer), url)
            for url in urls
        ]

    def _get_renderer(self) -> Optional[Any]:
        if self._renderer is None:
            import pagedistiller
            self._renderer = pagedistiller.default_renderer()
        return self._renderer

    @staticmethod
    def _to_entry(result: Any, requested_url: str) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "url": result.url or requested_url,
            "title": result.title,
            "content": result.content,
            "raw_content": result.content,
            "metadata": {"method": result.method},
        }
        if result.error:
            entry["error"] = result.error
        return entry
