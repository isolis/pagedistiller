"""``pagedistiller <url>`` -- a standalone CLI for manual testing, no hermes needed.

Usage::

    python -m pagedistiller https://example.com
    python -m pagedistiller https://example.com --json
    python -m pagedistiller https://example.com --no-render

Wraps :func:`pagedistiller.core.extract` directly -- no extraction logic lives
here beyond argument parsing and formatting the returned
:class:`~pagedistiller.core.Result`. The JS-rendering fallback (nodriver) is on
by default here: a CLI run is exactly the "does the whole chain actually work
end to end" check the render.py adapters exist for. ``--no-render`` opts back
out to the plain-fetch-only path.

Exit status is ``0`` when non-empty content came back, ``1`` otherwise -- so
the CLI is scriptable (``pagedistiller "$url" > out.txt || echo "failed"``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from .core import Result, extract


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pagedistiller",
        description="Fetch a URL and distill it to clean, boilerplate-free content.",
    )
    parser.add_argument("url", help="the URL to fetch and distill")
    parser.add_argument(
        "--no-render", action="store_true",
        help="disable the nodriver JS-rendering fallback; plain fetch only",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="print the full result (url, title, content, method, error) as JSON",
    )
    parser.add_argument(
        "--timeout", type=float, default=None,
        help="plain-fetch timeout in seconds (default: pagedistiller.fetch's own default)",
    )
    parser.add_argument(
        "--min-content-chars", type=int, default=None,
        help="thin-result threshold, in characters, before escalating to rendering",
    )
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> Result:
    extract_kwargs = {}
    if args.timeout is not None:
        extract_kwargs["timeout"] = args.timeout
    if args.min_content_chars is not None:
        extract_kwargs["min_content_chars"] = args.min_content_chars
    renderer = None
    if not args.no_render:
        from .render import default_renderer
        renderer = default_renderer()
    return extract(args.url, renderer=renderer, **extract_kwargs)


def _print_result(result: Result, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(
            {
                "url": result.url,
                "title": result.title,
                "content": result.content,
                "method": result.method,
                "error": result.error,
            },
            indent=2,
            ensure_ascii=False,
        ))
        return
    if result.title:
        print(result.title)
        print("=" * len(result.title))
    print(result.content)
    if result.error:
        print(f"\n[pagedistiller] {result.error}", file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    result = _run(args)
    _print_result(result, as_json=args.json)
    return 0 if result.content.strip() else 1
