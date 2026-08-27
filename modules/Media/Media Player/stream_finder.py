# Resolves a webpage URL to a direct .m3u8 HLS stream URL.
#
# Used by VideoPlayerPage's "Find Stream" button (video_player.py) so a
# user can paste a page URL — a stream site, an embed, a link that isn't
# itself a raw media file — instead of needing the direct manifest link
# that "Open URL" expects.
#
# Loads the page in headless Chromium via Playwright and watches every
# network request for the first one whose path ends in ".m3u8". No
# assumptions about page/player structure are made; this is pure network
# interception, so it works the same way regardless of which JS player
# the site uses.

from __future__ import annotations

import time
import urllib.parse


class StreamNotFoundError(Exception):
    """Raised when no .m3u8 request was observed before the timeout."""


def _is_m3u8_url(url: str) -> bool:
    """Checks the URL's path for a .m3u8 suffix, ignoring query strings
    (signed manifest URLs commonly carry tokens/expiry after a '?')."""
    return urllib.parse.urlparse(url).path.lower().endswith(".m3u8")


def find_m3u8_sync(page_url: str, timeout: float = 30.0) -> str:
    """Opens `page_url` in headless Chromium and returns the first .m3u8
    URL seen on the network (page requests, XHR/fetch, and anything
    loaded in popups/child frames the page spawns).

    Raises:
        RuntimeError: Playwright/Chromium isn't installed.
        StreamNotFoundError: no .m3u8 request appeared within `timeout`.

    This runs Playwright's *sync* API, which blocks the calling thread.
    Always call it from a background thread — never from the CTk main
    thread — and hand the result back via `.after(0, ...)` like the rest
    of this app's worker threads do (see mini_widget.py, remote_access_tab.py).
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    except ImportError as exc:
        raise RuntimeError(
            "Playwright isn't installed. Run: pip install playwright "
            "&& playwright install chromium"
        ) from exc

    found = {"url": None}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            raise RuntimeError(
                "Couldn't launch Chromium. Run: playwright install chromium"
            ) from exc

        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            def on_request(request):
                if found["url"] is None and _is_m3u8_url(request.url):
                    found["url"] = request.url

            # Catch requests from the page itself, and from any popup /
            # child page it opens (some embeds redirect the actual player
            # into a new tab/window).
            page.on("request", on_request)
            context.on("page", lambda new_page: new_page.on("request", on_request))

            try:
                page.goto(page_url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except PWTimeoutError:
                pass  # Navigation can time out while requests still stream in.
            except Exception as exc:
                print(f"[stream_finder] navigation error: {exc}")

            # Many players wait for a moment (or a synthetic play trigger)
            # before requesting the manifest, so keep watching network
            # traffic after the page itself has finished loading.
            deadline = time.monotonic() + timeout
            while found["url"] is None and time.monotonic() < deadline:
                page.wait_for_timeout(250)
        finally:
            browser.close()

    if found["url"] is None:
        raise StreamNotFoundError(f"No .m3u8 stream found on {page_url}")
    return found["url"]