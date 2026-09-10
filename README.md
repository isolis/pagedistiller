# PageDistiller

PageDistiller is a small, local, dependency-light tool that turns a URL into clean,
readable content — a title and boilerplate-free text/markdown body — without relying
on a third-party extraction API (Firecrawl, Exa, Keenable, etc.).

## Why

Most "web extraction" vendors are really just doing two cheap things on your behalf:
fetching a page and stripping out the nav/ads/boilerplate around the actual content.
For a handful of static-web-page fetches, that's not worth an external account, a
per-request network hop through someone else's infrastructure, or a self-hosted
service running 24/7 for occasional use. PageDistiller does the same job locally:

1. **Fetch** — plain HTTP GET (`httpx`), no browser, no rendering, for the common case
   of a normal static/server-rendered page.
2. **Distill** — run the HTML through `trafilatura` to strip boilerplate and produce
   clean text/markdown.
3. **Render fallback** — if the plain fetch comes back too thin (JS-rendered page that
   needs a real DOM) or looks like a bot-challenge wall, fall back to a local headless
   browser (`nodriver`, driving Chromium over CDP — runs JS and waits out Cloudflare/
   Turnstile-style challenges) to get rendered HTML, then distill that.

Everything runs on your own machine. The only network call is to the destination
site itself — never to a middleman extraction service.

## Non-goals

- Not a search engine or search index — that's a genuinely different problem
  (crawling/indexing the web), and out of scope here.
- Not a general browser-automation tool — no clicking, filling forms, or multi-step
  interaction. Given a URL, PageDistiller returns content. Nothing more.
- Not trying to match a paid vendor's anti-bot/proxy-rotation infrastructure. For a
  site that actively blocks non-browser traffic, PageDistiller will fail like any
  other local tool would: the plain fetch is tried first, and only then does the
  rendering fallback (a local headless browser that waits out the challenge) run.
  When neither produces content, an error is returned — never a fabricated result.

## Installation & Hermes Integration

### Quick Install (Automated)

Clone this repository and run [`install.sh`](install.sh):

```bash
git clone https://github.com/isolis/pagedistiller.git
cd pagedistiller
./install.sh
```

For live development (editable package install + symlinked plugin):

```bash
./install.sh --editable
```

To uninstall from Hermes:

```bash
./install.sh --uninstall
```

Run `./install.sh --help` for full options.

### Manual Installation

If you prefer to install manually:

1. **Install into Hermes's virtual environment**:
   ```bash
   ~/.hermes/hermes-agent/venv/bin/pip install .
   ```

2. **Deploy the plugin**:
   Copy [`hermes_plugin/pagedistiller/`](hermes_plugin/pagedistiller/) to Hermes's user plugin directory (so `hermes update` will not overwrite it):
   ```bash
   mkdir -p ~/.hermes/plugins/web
   cp -r hermes_plugin/pagedistiller ~/.hermes/plugins/web/
   ```

3. **Enable the plugin and set the extraction backend**:
   ```bash
   hermes plugins enable web/pagedistiller --no-allow-tool-override
   hermes config set web.extract_backend pagedistiller
   ```

4. **Verify**:
   Verify that PageDistiller is recognized as the active extract backend:
   ```bash
   ~/.hermes/hermes-agent/venv/bin/python -c "
   from tools.web_tools import _ensure_web_plugins_loaded
   _ensure_web_plugins_loaded()
   from agent.web_search_registry import get_active_extract_provider
   p = get_active_extract_provider()
   print('Active extract provider:', p.name if p else 'None')
   "
   ```

## Standalone CLI Usage

PageDistiller can also be used as a standalone command-line tool without Hermes:

```bash
# Install locally
pip install .

# Extract content from a URL
pagedistiller https://example.com
```

If you're working inside a clone of this repo and have a dev environment set up
(see [Running Tests](#running-tests) below), run it straight from the venv without
installing system-wide:

```bash
.venv/bin/pagedistiller https://example.com
# equivalently:
.venv/bin/python -m pagedistiller https://example.com
```

Flags:

```bash
# Output the full Result (url, title, content, method, error) as JSON
pagedistiller https://example.com --json

# Disable the nodriver JS-rendering fallback (plain fetch only)
pagedistiller https://example.com --no-render

# Override the plain-fetch timeout (seconds)
pagedistiller https://example.com --timeout 10

# Override the "thin result" threshold (chars) before escalating to rendering
pagedistiller https://example.com --min-content-chars 200
```

Exit status is `0` when non-empty content came back, `1` otherwise, so it's
scriptable: `pagedistiller "$url" > out.txt || echo "failed"`.

## Running Tests

Set up a virtual environment with the `test` extra and run `pytest` — there's no
separate test-runner script:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

If a venv is already set up (as it is in this repo's own checkout), just:

```bash
.venv/bin/python -m pytest
```

The suite is offline by default — no real network or browser is required. A few
tests in `tests/test_integration.py` opportunistically exercise a real renderer
(`nodriver`, when its Chromium binary is available) or a real network fetch
(`https://example.com`), and skip cleanly with a reason when the browser or
network isn't available, rather than failing.

## Origin

Built to replace hermes-agent's `web_extract` tool, which by default resolves to a
rotating set of anonymous "keyless" third-party extraction services (Exa, Parallel,
Firecrawl, Keenable). PageDistiller is designed to be usable standalone (its own
Python package, its own tests) and, on top of that, wired into hermes-agent as a
local `web.extract_backend` plugin — but the core library has no hermes dependency.

