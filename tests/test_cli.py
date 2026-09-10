"""``pagedistiller.cli.main``: argument parsing, result formatting, exit status.

``extract`` itself is monkeypatched -- these tests exercise CLI plumbing only,
not fetch/distill/render (those have their own test modules). Rendering is on
by default here, so a separate test confirms ``--no-render`` actually suppresses
it rather than just accepting the flag.
"""

import json

import pytest

import pagedistiller.cli as cli
import pagedistiller.render as render_module
from pagedistiller.core import Result


def _good_result(url="http://example.com") -> Result:
    return Result(url=url, title="A Title", content="Real body content.",
                  method="fetch", error=None)


def _empty_result(url="http://example.com") -> Result:
    return Result(url=url, title="", content="", method="fetch",
                  error="no content -- page likely needs JS rendering (no renderer available)")


def test_main_prints_title_and_content_exit_zero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "extract", lambda url, **kw: _good_result(url))
    monkeypatch.setattr(render_module, "default_renderer", lambda **kw: object())

    code = cli.main(["http://example.com"])

    out = capsys.readouterr().out
    assert code == 0
    assert "A Title" in out
    assert "Real body content." in out


def test_main_empty_content_exit_one_and_stderr_error(monkeypatch, capsys):
    monkeypatch.setattr(cli, "extract", lambda url, **kw: _empty_result(url))
    monkeypatch.setattr(render_module, "default_renderer", lambda **kw: object())

    code = cli.main(["http://example.com"])

    captured = capsys.readouterr()
    assert code == 1
    assert "needs JS rendering" in captured.err


def test_main_json_flag_emits_full_result(monkeypatch, capsys):
    monkeypatch.setattr(cli, "extract", lambda url, **kw: _good_result(url))
    monkeypatch.setattr(render_module, "default_renderer", lambda **kw: object())

    cli.main(["http://example.com", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "url": "http://example.com",
        "title": "A Title",
        "content": "Real body content.",
        "method": "fetch",
        "error": None,
    }


def test_main_renderer_built_by_default(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(render_module, "default_renderer", lambda **kw: calls.append(1) or object())

    seen_kwargs = {}
    def fake_extract(url, **kw):
        seen_kwargs.update(kw)
        return _good_result(url)
    monkeypatch.setattr(cli, "extract", fake_extract)

    cli.main(["http://example.com"])

    assert calls == [1]
    assert seen_kwargs.get("renderer") is not None


def test_main_no_render_skips_renderer(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(render_module, "default_renderer", lambda **kw: calls.append(1) or object())

    seen_kwargs = {}
    def fake_extract(url, **kw):
        seen_kwargs.update(kw)
        return _good_result(url)
    monkeypatch.setattr(cli, "extract", fake_extract)

    cli.main(["http://example.com", "--no-render"])

    assert calls == []
    assert seen_kwargs.get("renderer") is None


def test_main_forwards_timeout_and_min_content_chars(monkeypatch):
    seen_kwargs = {}
    def fake_extract(url, **kw):
        seen_kwargs.update(kw)
        return _good_result(url)
    monkeypatch.setattr(cli, "extract", fake_extract)
    monkeypatch.setattr(render_module, "default_renderer", lambda **kw: object())

    cli.main(["http://example.com", "--timeout", "5", "--min-content-chars", "42"])

    assert seen_kwargs["timeout"] == 5.0
    assert seen_kwargs["min_content_chars"] == 42


def test_main_requires_url_argument():
    with pytest.raises(SystemExit):
        cli.main([])
