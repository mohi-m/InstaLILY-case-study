"""Headful stealth Chromium pool for fetching PartSelect pages.

PartSelect blocks plain HTTP (403) and headless browsers, so we drive a REAL,
headful Chromium with stealth patches, a realistic Windows UA/headers, randomized
polite delays, and Cloudflare-challenge retry/backoff.

A small pool of pages (default 4) is shared via an asyncio.Queue so callers can
fetch concurrently up to the pool size.
"""

import asyncio
import os
import random

from playwright.async_api import async_playwright

from robots import USER_AGENT, RobotsGate

# Conservative defaults after an IP block: single page, long randomized delays.
MIN_DELAY = float(os.getenv("SCRAPE_MIN_DELAY", "8"))
MAX_DELAY = float(os.getenv("SCRAPE_MAX_DELAY", "18"))
POOL_SIZE = int(os.getenv("SCRAPE_POOL_SIZE", "1"))
NAV_TIMEOUT = int(os.getenv("SCRAPE_NAV_TIMEOUT_MS", "60000"))

CF_MARKERS = ("Just a moment", "Checking your browser", "cf-challenge", "Attention Required")


class BrowserPool:
    """Async context manager owning a headful browser and a queue of ready pages."""

    def __init__(self, size: int = POOL_SIZE, robots: RobotsGate | None = None) -> None:
        self.size = max(1, size)
        self.robots = robots
        self._pw = None
        self._browser = None
        self._contexts: list = []
        self._pages: asyncio.Queue = asyncio.Queue()

    async def __aenter__(self) -> "BrowserPool":
        self._pw = await async_playwright().start()
        # headless=False is REQUIRED — headless Chromium gets blocked by PartSelect.
        self._browser = await self._pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        try:
            from playwright_stealth import stealth_async
        except Exception:
            stealth_async = None

        for _ in range(self.size):
            ctx = await self._browser.new_context(
                user_agent=USER_AGENT,
                locale="en-US",
                viewport={"width": 1366, "height": 900},
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            page = await ctx.new_page()
            if stealth_async:
                try:
                    await stealth_async(page)
                except Exception:
                    pass
            self._contexts.append(ctx)
            await self._pages.put(page)
        return self

    async def __aexit__(self, *exc) -> None:
        for ctx in self._contexts:
            try:
                await ctx.close()
            except Exception:
                pass
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _polite_sleep(self) -> None:
        delay = (self.robots.crawl_delay if self.robots else None) or random.uniform(
            MIN_DELAY, MAX_DELAY
        )
        await asyncio.sleep(delay)

    async def fetch(self, url: str, retries: int = 3) -> str | None:
        """Navigate to url on a pooled page and return HTML, or None if blocked/disallowed."""
        if self.robots and not self.robots.allowed(url):
            return None
        page = await self._pages.get()
        try:
            for attempt in range(retries):
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                    html = await page.content()
                    if any(marker in html for marker in CF_MARKERS):
                        await asyncio.sleep(5 * (attempt + 1))  # let challenge settle
                        continue
                    return html
                except Exception:
                    await asyncio.sleep(2 ** (attempt + 1))
            return None
        finally:
            await self._polite_sleep()
            await self._pages.put(page)
