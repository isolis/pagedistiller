"""HTML -> clean, boilerplate-free content via trafilatura.

Given raw HTML, returns the page's title and its main text/markdown body with
navigation, ads, and footer boilerplate stripped out. This is the single thing a
third-party "extraction" vendor charges for that turns out to be just "run a
content extractor on the markup" -- so we do it locally.

The returned body is free of trafilatura's YAML front-matter header (title/url/
date metadata), which is why it is stripped rather than returned as-is.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_INCLUDE_LINKS = False
DEFAULT_MARKDOWN = False


@dataclass(frozen=True)
class Distilled:
    """The distilled view of one page.

    ``content`` is the cleaned body in the requested format (plain text by
    default, Markdown when ``markdown`` is set). ``title`` is ``""`` when the page
    had no detectable title. An un-distillable page (e.g. a JS shell that produced
    nothing) yields ``content == ""``, the signal the orchestration layer uses to
    escalate to a JS-rendering fallback.
    """

    title: str
    content: str
    url: str


def distill(html: str, url: str | None = None, *,
            include_links: bool = DEFAULT_INCLUDE_LINKS,
            markdown: bool = DEFAULT_MARKDOWN) -> Distilled:
    """Distill raw ``html`` from ``url`` into a :class:`Distilled` page.

    ``markdown`` selects the body format: ``False`` yields plain text, ``True``
    yields Markdown; both are trafilatura's own output and callers pick one. An
    empty body (``""``) means trafilatura found no distillable content.
    """
    from trafilatura import extract_with_metadata  # lazy: heavy deps off import

    document = extract_with_metadata(
        html,
        url=url,
        include_formatting=markdown,
        include_links=include_links,
    )
    if document is None:
        return Distilled(title="", content="", url=url or "")

    content = _strip_front_matter(document.text or "")
    return Distilled(
        title=(document.title or "").strip(),
        content=content.strip(),
        url=url or "",
    )


def _strip_front_matter(text: str) -> str:
    """Remove trafilatura's leading YAML front-matter block, if present.

    trafilatura's ``Document.text`` opens with a ``---`` delimited header
    (``title:`` / ``url:`` / ``date:`` / ...). Only the first such block is
    stripped; a later one (rare, only if the body itself carries it) is left as
    data. A body that does not start with ``---`` is returned unchanged.
    """
    if not text.startswith("---"):
        return text
    lines = text.split("\n")
    # Line 0 is the opening "---"; drop through the closing delimiter.
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).lstrip("\n")
    return text
