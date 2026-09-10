"""render(): the JS-rendering fallback chain, default engine nodriver.

Every test is offline and browser-free: engines are built with injected fake
``run`` callables, so the ordering, the failure-skip, the deadline cap, and the
"missing engine yields nothing" contract are all exercised without launching a
browser or touching the network. The real nodriver/Chromium/Lightpanda adapters
have their subprocess calls intercepted (binary presence faked via
``shutil.which`` / ``_chromium_binary``) so the exact argv each one shells out
to is pinned by a test, never executed here.
"""

import subprocess
import sys

import pagedistiller.render as render_module
from pagedistiller.render import (
    Engine,
    chromium,
    default_engines,
    default_renderer,
    lightpanda,
    nodriver,
    render_chain,
)


def _engine(method, run, *, enabled=True):
    return Engine(method, run, enabled=lambda: enabled)


def test_chain_prefers_first_engine_that_serves():
    seen = []

    def lp(url, timeout):
        seen.append("lightpanda")
        return "<html><body>lightpanda body, enough to keep</body></html>"

    def cr(url, timeout):
        seen.append("chromium")
        return "<html><body>chromium body</body></html>"

    engines = [_engine("lightpanda", lp), _engine("chromium", cr)]
    out = list(render_chain("http://example.com", engines=engines))

    assert out == [("lightpanda", "<html><body>lightpanda body, enough to keep</body></html>")]
    assert seen == ["lightpanda"]  # chromium never reached


def test_chain_falls_through_to_chromium_when_lightpanda_empty():
    def lp(url, timeout):
        return ""  # rendered nothing worth keeping -> fall through

    def cr(url, timeout):
        return "<html><body>chromium saved the day, plenty of content</body></html>"

    engines = [_engine("lightpanda", lp), _engine("chromium", cr)]
    out = list(render_chain("http://example.com", engines=engines))

    assert out == [("chromium", "<html><body>chromium saved the day, plenty of content</body></html>")]


def test_chain_skips_engine_that_raises():
    def lp(url, timeout):
        raise RuntimeError("lightpanda crashed")

    def cr(url, timeout):
        return "<html><body>chromium recovered</body></html>"

    engines = [_engine("lightpanda", lp), _engine("chromium", cr)]
    out = list(render_chain("http://example.com", engines=engines))
    assert out[0][0] == "chromium"


def test_chain_yields_nothing_when_all_engines_empty():
    engines = [
        _engine("lightpanda", lambda u, t: None),
        _engine("chromium", lambda u, t: "   "),
    ]
    out = list(render_chain("http://example.com", engines=engines))
    assert out == []


def test_chain_skips_unavailable_engine_without_running():
    ran = []

    def lp(url, timeout):
        ran.append("lightpanda")
        return None

    def cr(url, timeout):
        ran.append("chromium")
        return "<html><body>chromium only</body></html>"

    engines = [_engine("lightpanda", lp, enabled=False), _engine("chromium", cr)]
    out = list(render_chain("http://example.com", engines=engines))
    assert out == [("chromium", "<html><body>chromium only</body></html>")]
    assert ran == ["chromium"]  # the unavailable lightpanda was not invoked


def test_chain_abandons_remaining_engines_after_deadline():
    import time

    def lp(url, timeout):
        time.sleep(0.05)
        return None

    def cr(url, timeout):
        return "<html><body>too late</body></html>"

    ran = []

    def tracker(url, timeout):
        ran.append("chromium")
        return None

    engines = [
        _engine("lightpanda", lp),
        _engine("chromium", cr),
        _engine("last", tracker),
    ]
    out = list(render_chain("http://example.com", engines=engines, total_deadline=0.01))
    # Deadline (0.01s) is exceeded before chromium runs, so nothing is yielded and
    # the "last" engine is never touched -- the chain stops rather than running on.
    assert out == []
    assert "chromium" not in ran
    assert "last" not in ran


def test_engine_run_returns_none_on_subprocess_success_is_not_assumed():
    # The chain contract: only non-empty stripped HTML is a "served" signal.
    def cr(url, timeout):
        return "   \n  "
    out = list(render_chain("http://example.com", engines=[_engine("chromium", cr)]))
    assert out == []


def test_default_renderer_returns_a_callable_yielding_a_generator():
    renderer = default_renderer()
    assert callable(renderer)
     # Calling it returns a lazy generator, not an eager list.
    result = renderer("http://example.com")
    assert hasattr(result, "__iter__") and not isinstance(result, (list, tuple))


def test_default_engines_is_nodriver_only():
    # nodriver (Chromium over CDP) supersedes both lightpanda and the plain
    # --dump-dom chromium adapter as the default -- it can run JS *and* wait
    # out a bot challenge, which neither of the other two can do.
    engines = default_engines()
    assert [e.method for e in engines] == ["nodriver"]


def test_default_renderer_yields_pairs_when_consulted():
    renderer = default_renderer()
    out = list(renderer("http://example.com"))
    for pair in out:
        assert len(pair) == 2   # (method, html)


# --- real-adapter argv (subprocess call intercepted, never actually run) ----
#
# Regression coverage: lightpanda() used to shell out to `lightpanda serve`, which
# starts a long-running CDP server rather than rendering one page and exiting --
# it never takes a URL argument and never produces stdout, so every call just
# hung for the full attempt_timeout. These tests pin the exact argv so that
# mistake (or one like it) fails immediately instead of only showing up as a
# silent 30s hang against a real installed binary.

def test_lightpanda_shells_out_to_one_shot_fetch_dump(monkeypatch):
    monkeypatch.setattr(render_module.shutil, "which", lambda name: "/usr/bin/lightpanda")

    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="<html>ok</html>", stderr="")

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)

    engine = lightpanda()
    assert engine.is_available() is True
    html = engine.render("http://example.com", 5.0)

    assert html == "<html>ok</html>"
    assert seen["argv"] == [
        "/usr/bin/lightpanda", "fetch", "--dump", "html", "http://example.com",
    ]
    assert "serve" not in seen["argv"]


def test_chromium_shells_out_to_headless_dump_dom(monkeypatch):
    monkeypatch.setattr(
        render_module, "_chromium_binary", lambda: "/usr/bin/chromium"
    )

    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="<html>rendered</html>", stderr="")

    monkeypatch.setattr(render_module.subprocess, "run", fake_run)

    engine = chromium()
    html = engine.render("http://example.com", 5.0)

    assert html == "<html>rendered</html>"
    assert seen["argv"] == [
        "/usr/bin/chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
        "--dump-dom", "http://example.com",
    ]


# --- nodriver: availability, argv, and the timeout process-group kill --------


class _FakeCompletedProc:
    """Minimal stand-in for a Popen that returned normally."""

    def __init__(self, pid, returncode, stdout, stderr):
        self.pid = pid
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, timeout=None):
        return self._stdout, self._stderr


def test_nodriver_available_requires_chromium_binary(monkeypatch):
    # nodriver the library is a real dependency here, so import succeeds; the
    # engine is only "available" once a Chromium-family binary is also found.
    monkeypatch.setattr(render_module, "_chromium_binary", lambda: None)
    assert nodriver().is_available() is False

    monkeypatch.setattr(render_module, "_chromium_binary", lambda: "/usr/bin/chromium")
    assert nodriver().is_available() is True


def test_nodriver_unavailable_when_library_missing(monkeypatch):
    # sys.modules[name] = None makes a subsequent `import name` raise
    # ImportError -- simulates nodriver not being installed, without needing
    # to actually uninstall it.
    monkeypatch.setattr(render_module, "_chromium_binary", lambda: "/usr/bin/chromium")
    monkeypatch.setitem(sys.modules, "nodriver", None)
    assert nodriver().is_available() is False


def test_nodriver_run_builds_expected_argv(monkeypatch):
    monkeypatch.setattr(render_module, "_chromium_binary", lambda: "/usr/bin/chromium")

    seen = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeCompletedProc(4242, 0, "<html>rendered by nodriver</html>", "")

    monkeypatch.setattr(render_module.subprocess, "Popen", fake_popen)

    html = render_module._subprocess_nodriver_dump("http://example.com", 5.0)

    assert html == "<html>rendered by nodriver</html>"
    assert seen["argv"] == [
        sys.executable, "-m", "pagedistiller._browser_dump",
        "http://example.com", "5.0", "/usr/bin/chromium",
    ]
    # Its own process group, so a timeout can kill Chrome along with it.
    assert seen["kwargs"]["start_new_session"] is True


def test_nodriver_run_without_chromium_binary_omits_it_from_argv(monkeypatch):
    monkeypatch.setattr(render_module, "_chromium_binary", lambda: None)

    seen = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        return _FakeCompletedProc(1, 0, "<html>ok</html>", "")

    monkeypatch.setattr(render_module.subprocess, "Popen", fake_popen)

    render_module._subprocess_nodriver_dump("http://example.com", 5.0)
    assert seen["argv"] == [
        sys.executable, "-m", "pagedistiller._browser_dump",
        "http://example.com", "5.0",
    ]


def test_nodriver_run_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(render_module, "_chromium_binary", lambda: None)
    monkeypatch.setattr(
        render_module.subprocess, "Popen",
        lambda argv, **kw: _FakeCompletedProc(1, 1, "", "boom"),
    )
    assert render_module._subprocess_nodriver_dump("http://example.com", 5.0) is None


def test_nodriver_run_kills_whole_process_group_on_timeout(monkeypatch):
    # A plain proc.kill() on timeout only reaches the direct child (the
    # _browser_dump interpreter); nodriver's actual Chrome is a grandchild in
    # the same group and would otherwise be orphaned. Regression coverage for
    # that leak: timeout must route through os.killpg on the whole group.
    monkeypatch.setattr(render_module, "_chromium_binary", lambda: None)

    class _HangingProc:
        pid = 999
        returncode = -9

        def __init__(self):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(cmd="nodriver", timeout=timeout)
            return "", ""

        def kill(self):
            pass

    monkeypatch.setattr(render_module.subprocess, "Popen", lambda argv, **kw: _HangingProc())

    killed = {}
    monkeypatch.setattr(render_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        render_module.os, "killpg",
        lambda pgid, sig: killed.update(pgid=pgid, sig=sig),
    )

    html = render_module._subprocess_nodriver_dump("http://example.com", 0.01)

    assert html is None
    assert killed == {"pgid": 999, "sig": render_module.signal.SIGKILL}
