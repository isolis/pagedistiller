"""Subprocess helper for nodriver headless rendering.

Invoked as:
    python -m pagedistiller._browser_dump <url> <timeout_seconds> [browser_executable_path]

Navigates to URL using nodriver, waits for Cloudflare / bot challenge resolution
and dynamic DOM hydration, and writes rendered HTML to stdout.
"""

from __future__ import annotations

import asyncio
import sys


async def _run(url: str, timeout: float, browser_bin: str | None = None) -> None:
    try:
        import nodriver as uc
    except ImportError:
        sys.stderr.write("nodriver is not installed\n")
        sys.exit(1)

    browser_args = [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
    ]

    try:
        browser = await uc.start(
            browser_executable_path=browser_bin,
            headless=True,
            sandbox=False,
            browser_args=browser_args,
        )
    except Exception as exc:
        sys.stderr.write(f"failed to start browser: {exc}\n")
        sys.exit(1)

    try:
        page = await browser.get(url)

        # Cloudflare / bot challenge settling loop
        # Check if the title or body indicates an active challenge
        loop = asyncio.get_event_loop()
        start = loop.time()
        challenge_deadline = min(timeout - 1.0, 15.0)

        while (loop.time() - start) < challenge_deadline:
            is_active_challenge = False
            try:
                title = await page.evaluate("document.title")
                title_str = str(title or "").lower()
                if "just a moment" in title_str or "attention required" in title_str:
                    is_active_challenge = True
            except Exception:
                pass

            if not is_active_challenge:
                break
            await asyncio.sleep(0.5)

        # Brief settle delay for JS frameworks / client hydration
        await asyncio.sleep(0.5)

        content = await page.get_content()
        if content and content.strip():
            sys.stdout.write(content)
            sys.stdout.flush()
    except Exception as exc:
        sys.stderr.write(f"navigation failed for {url}: {exc}\n")
        sys.exit(1)
    finally:
        try:
            browser.stop()
        except Exception:
            pass


def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: python -m pagedistiller._browser_dump <url> [timeout] [browser_bin]\n")
        sys.exit(1)

    url = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    browser_bin = None
    if len(sys.argv) > 3 and sys.argv[3] and sys.argv[3] != "None":
        browser_bin = sys.argv[3]

    asyncio.run(_run(url, timeout, browser_bin))


if __name__ == "__main__":
    main()
