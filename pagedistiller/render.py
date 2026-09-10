"""JS-rendering fallback: a Renderer chain that turns a URL into rendered HTML.

The common case -- a normal static or server-rendered page -- is served by the
plain HTTP fetch in :mod:`pagedistiller.fetch` and distilled directly. Some pages
are a JS shell (their real body is produced only after script execution) or sit
behind a bot-challenge wall (Cloudflare Turnstile and the like). Those need a
real, settled DOM. This module is that rung.

The default chain is a single engine: :func:`nodriver`, driving Chromium over
CDP with no automation flags. It supersedes the two earlier single-purpose
adapters below it -- :func:`lightpanda` (a small, fast headless browser, no CDP
client needed) and :func:`chromium` (plain ``--dump-dom``) -- neither of which
can wait out a bot challenge; nodriver can run JS *and* pass one, so it replaced
both as the default rather than sitting alongside them. Both remain here,
individually usable, for callers who want a lighter engine and do not need
challenge-solving.

This module hands back a :data:`~pagedistiller.core.Renderer`: a generator that
yields one ``(method, rendered_html)`` pair per engine that actually produced
non-empty HTML. :mod:`pagedistiller.core` feeds each pair back through
:mod:`pagedistiller.distill` and keeps the first that is not thin, so the
renderer itself does not need to know about the thin-result heuristic -- it just
produces HTML and names which engine made it.

Engines are reached through :class:`Engine` records carrying a ``run`` callable
(URL, timeout) -> ``Optional[str]`` of HTML. The default engines are real
subprocess adapters (:func:`nodriver` / :func:`lightpanda` / :func:`chromium`);
callers may inject their own ``run`` (e.g. an in-process fake) so the whole
chain is unit-testable with no browser and no network.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Tuple

from .core import Renderer

logger = logging.getLogger(__name__)

# Per-engine wall-clock cap and the overall budget for the whole chain. A single
# stubborn URL must never be allowed to hang the caller: each attempt and the sum
# of attempts are both bounded.
DEFAULT_ATTEMPT_TIMEOUT = 30.0
DEFAULT_TOTAL_DEADLINE = 60.0


class Engine:
    """One rung of the render chain: a named engine with a way to run it.

    ``method`` is the name recorded in ``Result.method`` when this engine serves
    a page. ``run`` renders ``url`` and returns the rendered HTML, or ``None``
    when it could not produce any (binary absent, process failed, timed out, or
    the page yielded nothing to distill). ``enabled`` reports whether the engine
    can run here without launching it -- the default adapters probe for the
    binary -- so a missing engine is skipped, not reported as a page failure.
    """

    def __init__(
        self,
        method: str,
        run: Callable[[str, float], Optional[str]],
        *,
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self.method = method
        self._run = run
        self._enabled = enabled

    def is_available(self) -> bool:
        """True when this engine can run in the current environment."""
        try:
            return self._enabled()
        except Exception:
            return False

    def render(self, url: str, timeout: float) -> Optional[str]:
        """Render ``url``; return HTML, or ``None`` when this engine served nothing."""
        return self._run(url, timeout)


def render_chain(
    url: str,
    *,
    engines: Iterable[Engine],
    attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT,
    total_deadline: float = DEFAULT_TOTAL_DEADLINE,
) -> Iterator[Tuple[str, str]]:
    """Yield ``(method, html)`` for each engine that serves non-empty HTML.

    Engines are tried in iteration order (nodriver alone, by default -- see
    :func:`default_engines`). Only an engine that returns non-empty HTML is
    yielded; an engine that returns ``None`` or raises is logged and the next
    one is tried. An unavailable engine (``is_available()`` false -- e.g. its
    binary is not installed) is skipped without running, so a missing
    optional engine is not mistaken for a page that could not be rendered.

    The ``total_deadline`` is a wall-clock budget for the whole chain: once
    elapsed, remaining engines are abandoned rather than let one stubborn URL run
    past the cap. ``attempt_timeout`` bounds each individual engine.
    """
    import time

    start = time.monotonic()
    for engine in engines:
        if not engine.is_available():
            logger.debug("render engine %s unavailable; skipping", engine.method)
            continue
        if time.monotonic() - start > total_deadline:
            logger.warning(
                "render deadline (%.0fs) exceeded before %s; stopping chain",
                total_deadline,
                engine.method,
            )
            return
        try:
            html = engine.render(url, attempt_timeout)
        except Exception as exc:
            logger.debug("render engine %s failed for %s: %s", engine.method, url, exc)
            continue
        if html and html.strip():
            yield engine.method, html
            return


Runner = Callable[[str, float], Optional[str]]


def _subprocess_dump(argv: List[str], *, method: str) -> Runner:
    """Build a runner that renders via a headless browser's HTML-dump subcommand.

    ``argv`` is the full command *without* the URL -- a resolved binary plus its
    flags -- and the runner appends ``url`` as the final positional. It returns
    ``None`` when the process fails, so the chain simply moves on. A non-zero exit
    or empty output is a "this engine could not serve it" signal, not a crash.
    """

    def run(url: str, timeout: float) -> Optional[str]:
        proc_args = [*argv, url]
        try:
            proc = subprocess.run(     # noqa: S603 - argv is fixed + a validated URL
                proc_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            logger.debug("%s timed out for %s", method, url)
            return None
        if proc.returncode != 0:
            logger.debug("%s exited %d for %s", method, proc.returncode, url)
            return None
        html = proc.stdout or ""
        return html if html.strip() else None

    return run


def lightpanda(attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT) -> Engine:
    """The Lightpanda engine, when its binary is installed -- else disabled.

    Lightpanda is the fast, light first choice. The default adapter uses its
    one-shot ``fetch --dump html`` subcommand (render the page, run its scripts,
    print the resulting HTML to stdout, then exit) -- not ``lightpanda serve``,
    which starts a long-running CDP server that never takes a URL argument and
    never exits on its own; running that under a subprocess timeout would just
    hang for the full timeout on every call. Only reachable when ``lightpanda``
    is on PATH, so hosts without it simply skip to Chromium.
    """

    def available() -> bool:
        return shutil.which("lightpanda") is not None

    def run(url: str, timeout: float) -> Optional[str]:
        binary = shutil.which("lightpanda")
        if binary is None:
            logger.debug(
                "lightpanda unavailable: not on PATH; install from "
                "https://lightpanda.io/docs/run-locally/installation",
            )
            return None
        return _subprocess_dump(
            [binary, "fetch", "--dump", "html"],
            method="lightpanda",
        )(url, timeout)

    return Engine("lightpanda", run, enabled=available)


_CHROMIUM_BINARIES = (
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
    "google-chrome-stable",
)


def _chromium_binary() -> Optional[str]:
    """First Chromium-family binary found on PATH, common cache, or system paths, or None."""
    env_bin = os.environ.get("PAGEDISTILLER_CHROME_BIN") or os.environ.get("CHROME_BIN")
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin

    for name in _CHROMIUM_BINARIES:
        found = shutil.which(name)
        if found:
            return found

    # Check Playwright cached browsers if present
    try:
        pw_root = Path.home() / ".cache" / "ms-playwright"
        if pw_root.is_dir():
            for candidate in pw_root.glob("**/chrome"):
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
    except Exception:
        pass

    # Check common system installation paths
    for candidate in ("/snap/bin/chromium", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return None


def _kill_process_group(proc: "subprocess.Popen[str]") -> None:
    """SIGKILL every process in ``proc``'s group -- the Chrome it spawned included.

    ``proc.kill()`` alone only reaches the direct child (the ``_browser_dump``
    interpreter); the actual Chrome process nodriver starts is a grandchild of
    that, in the same group. Killing just the direct child on timeout leaves
    Chrome running, orphaned and reparented to init.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def _subprocess_nodriver_dump(url: str, timeout: float) -> Optional[str]:
    """Render url via nodriver in an isolated subprocess.

    Launched in its own process group (POSIX ``start_new_session``) so a
    timeout can kill the whole group at once -- see :func:`_kill_process_group`.
    """
    binary = _chromium_binary()
    proc_args = [
        sys.executable,
        "-m",
        "pagedistiller._browser_dump",
        url,
        str(timeout),
    ]
    if binary is not None:
        proc_args.append(binary)

    try:
        proc = subprocess.Popen(
            proc_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    except Exception as exc:
        logger.debug("nodriver subprocess failed to start for %s: %s", url, exc)
        return None

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        proc.communicate()
        logger.debug("nodriver timed out for %s", url)
        return None

    if proc.returncode != 0:
        logger.debug("nodriver exited %d for %s: %s", proc.returncode, url, stderr)
        return None
    return stdout if stdout and stdout.strip() else None


def nodriver(attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT) -> Engine:
    """The nodriver fallback engine: Chromium driven over CDP without automation flags.

    Solves JavaScript-rendered pages (SPAs) and passes Cloudflare Turnstile / bot
    challenges by running an isolated headless browser and waiting for challenge
    resolution before dumping the settled DOM.
    """

    def available() -> bool:
        try:
            import nodriver  # noqa: F401
            return _chromium_binary() is not None
        except ImportError:
            return False

    def run(url: str, timeout: float) -> Optional[str]:
        if not available():
            logger.debug("nodriver unavailable; missing library or chrome binary")
            return None
        return _subprocess_nodriver_dump(url, timeout)

    return Engine("nodriver", run, enabled=available)


def chromium(attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT) -> Engine:
    """The Chromium fallback engine, driven over an HTML dump of the rendered DOM.

    The default adapter uses Chromium's headless ``--dump-dom`` so it needs no
    third-party CDP library: Chromium renders the page (running its scripts) and
    prints the resulting DOM to stdout, which we hand back to the distill step.
    Only reachable when a Chromium binary is on PATH.
    """

    def available() -> bool:
        return _chromium_binary() is not None

    def run(url: str, timeout: float) -> Optional[str]:
        binary = _chromium_binary()
        if binary is None:
            logger.debug("chromium unavailable; no binary on PATH")
            return None
        return _subprocess_dump(
            [
                binary,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--dump-dom",
            ],
            method="chromium",
        )(url, timeout)

    return Engine("chromium", run, enabled=available)


def default_engines() -> List[Engine]:
    """nodriver (Chromium via CDP) as the primary fallback engine."""
    return [nodriver()]


def default_renderer(
    *,
    attempt_timeout: float = DEFAULT_ATTEMPT_TIMEOUT,
    total_deadline: float = DEFAULT_TOTAL_DEADLINE,
) -> Renderer:
    """A :data:`~pagedistiller.core.Renderer` over the default engine chain.

    Returns a generator function that, per URL, runs the default fallback engine
    (nodriver) and yields non-empty HTML when successful. Wire it into
    :func:`pagedistiller.core.extract` as the ``renderer`` argument to enable the
    fallback; when no engine is installed it yields nothing and ``extract``
    falls back to the plain-fetch result honestly, with no disguised success.
    """

    engines = default_engines()

    def renderer(url: str) -> Iterator[Tuple[str, str]]:
        yield from render_chain(
            url,
            engines=engines,
            attempt_timeout=attempt_timeout,
            total_deadline=total_deadline,
        )

    return renderer
