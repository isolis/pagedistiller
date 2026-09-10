"""hermes_plugin/pagedistiller: the Hermes web-search-provider adapter.

``PageDistillerWebSearchProvider`` subclasses ``agent.web_search_provider.
WebSearchProvider``, which lives in the separate hermes-agent codebase, not in
this repo (see README.md's "no hermes dependency" line for the core library --
the adapter is the one place that dependency is meant to live). This whole
module is skipped, cleanly, when that ABC isn't importable, so pagedistiller's
own suite stays fully standalone/offline anywhere hermes-agent isn't checked
out. On a dev machine that has it at the conventional ``~/.hermes/hermes-agent``
location, that path is added to ``sys.path`` for this discovery attempt only --
never assumed to exist.

Everything below tests the adapter's *mapping*: pagedistiller.extract() is
monkeypatched, so no network/browser call happens here either (see
test_core.py / test_render.py for those).
"""

import sys
from pathlib import Path

import pytest


def _hermes_agent_importable() -> bool:
    try:
        import agent.web_search_provider  # noqa: F401
        return True
    except ImportError:
        pass
    conventional = Path.home() / ".hermes" / "hermes-agent"
    if conventional.is_dir() and str(conventional) not in sys.path:
        sys.path.insert(0, str(conventional))
    try:
        import agent.web_search_provider  # noqa: F401
        return True
    except ImportError:
        return False


if not _hermes_agent_importable():
    pytest.skip(
        "hermes-agent (agent.web_search_provider) not importable -- "
        "skipping the plugin-adapter tests",
        allow_module_level=True,
    )

import pagedistiller
from agent.web_search_provider import WebSearchProvider
from hermes_plugin.pagedistiller.provider import PageDistillerWebSearchProvider


def _provider() -> PageDistillerWebSearchProvider:
    return PageDistillerWebSearchProvider()


def test_is_a_web_search_provider():
    assert isinstance(_provider(), WebSearchProvider)


def test_identity():
    p = _provider()
    assert p.name == "pagedistiller"
    assert p.display_name == "PageDistiller"


def test_extract_only_capability_flags():
    p = _provider()
    assert p.supports_search() is False
    assert p.supports_extract() is True


def test_is_available_true_when_pagedistiller_importable():
    assert _provider().is_available() is True


def test_is_available_false_when_pagedistiller_not_importable(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "pagedistiller":
            raise ImportError("simulated: pagedistiller not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    assert _provider().is_available() is False


def test_extract_maps_result_onto_hermes_contract(monkeypatch):
    def fake_extract(url, renderer=None, **kwargs):
        assert renderer is not None  # the renderer fallback is wired in
        return pagedistiller.Result(
            url=url, title="A Title", content="Real body content.",
            method="fetch", error=None,
        )

    monkeypatch.setattr(pagedistiller, "extract", fake_extract)

    results = _provider().extract(["http://example.com"])

    assert results == [{
        "url": "http://example.com",
        "title": "A Title",
        "content": "Real body content.",
        "raw_content": "Real body content.",
        "metadata": {"method": "fetch"},
    }]


def test_extract_includes_error_field_only_on_failure(monkeypatch):
    def fake_extract(url, renderer=None, **kwargs):
        return pagedistiller.Result(
            url=url, title="", content="", method="fetch",
            error="no content -- page likely needs JS rendering (no renderer available)",
        )

    monkeypatch.setattr(pagedistiller, "extract", fake_extract)

    [entry] = _provider().extract(["http://example.com"])
    assert entry["error"] == "no content -- page likely needs JS rendering (no renderer available)"
    assert entry["content"] == ""


def test_extract_preserves_url_order_and_count(monkeypatch):
    def fake_extract(url, renderer=None, **kwargs):
        return pagedistiller.Result(url=url, title="", content=f"body for {url}",
                                    method="fetch", error=None)

    monkeypatch.setattr(pagedistiller, "extract", fake_extract)

    urls = ["http://a.example", "http://b.example", "http://c.example"]
    results = _provider().extract(urls)

    assert [r["url"] for r in results] == urls
    assert [r["content"] for r in results] == [f"body for {u}" for u in urls]


def test_extract_ignores_unknown_kwargs(monkeypatch):
    monkeypatch.setattr(
        pagedistiller, "extract",
        lambda url, renderer=None, **kwargs: pagedistiller.Result(
            url=url, title="", content="ok", method="fetch", error=None,
        ),
    )
    # Hermes's dispatcher always passes format=...; other kwargs may appear too.
    results = _provider().extract(["http://example.com"], format="markdown",
                                  include_raw=True, max_chars=500)
    assert results[0]["content"] == "ok"


def test_extract_reuses_one_renderer_across_calls(monkeypatch):
    built = []
    monkeypatch.setattr(
        pagedistiller, "default_renderer",
        lambda **kw: built.append(object()) or built[-1],
    )
    monkeypatch.setattr(
        pagedistiller, "extract",
        lambda url, renderer=None, **kwargs: pagedistiller.Result(
            url=url, title="", content="ok", method="fetch", error=None,
        ),
    )

    p = _provider()
    p.extract(["http://a.example"])
    p.extract(["http://b.example"])

    assert len(built) == 1
