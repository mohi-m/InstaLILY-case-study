"""Headful stealth Chromium pool for fetching PartSelect pages.

PartSelect blocks plain HTTP (403) and headless browsers, so we drive a REAL,
headful Chromium with stealth patches, a realistic Windows UA/headers, randomized
polite delays, and Cloudflare-challenge retry/backoff.

A small pool of pages (default 4) is shared via an asyncio.Queue so callers can
fetch concurrently up to the pool size.
"""

import asyncio
import logging
import os
import random

from playwright.async_api import async_playwright

from robots import USER_AGENT, RobotsGate

logger = logging.getLogger(__name__)

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
        logger.info("Launching headful Chromium (pool size=%d)", self.size)
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
            logger.debug("playwright-stealth loaded")
        except Exception:
            stealth_async = None
            logger.warning("playwright-stealth not installed — running without stealth patches")

        for i in range(self.size):
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
            logger.debug("Browser page %d/%d ready", i + 1, self.size)
        return self

    async def __aexit__(self, *exc) -> None:
        logger.info("Shutting down browser pool")
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
        # Honour crawl-delay from robots.txt when present; otherwise use the
        # configured random window so we don't hammer the server.
        delay = (self.robots.crawl_delay if self.robots else None) or random.uniform(
            MIN_DELAY, MAX_DELAY
        )
        logger.debug("Polite delay %.1fs", delay)
        await asyncio.sleep(delay)

    async def fetch(self, url: str, retries: int = 3) -> str | None:
        """Navigate to url on a pooled page and return HTML, or None if blocked/disallowed."""
        if self.robots and not self.robots.allowed(url):
            logger.info("robots.txt disallows %s — skipping", url)
            return None
        page = await self._pages.get()
        try:
            for attempt in range(retries):
                try:
                    logger.debug("Fetching %s (attempt %d/%d)", url, attempt + 1, retries)
                    await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                    html = await page.content()
                    if any(marker in html for marker in CF_MARKERS):
                        # Cloudflare challenge — wait for it to auto-resolve before retrying.
                        wait = 5 * (attempt + 1)
                        logger.warning("Cloudflare challenge on %s — waiting %ds (attempt %d/%d)",
                                       url, wait, attempt + 1, retries)
                        await asyncio.sleep(wait)
                        continue
                    return html
                except Exception as exc:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Navigation error on %s: %s — retrying in %ds", url, exc, wait)
                    await asyncio.sleep(wait)
            logger.error("All %d attempts failed for %s", retries, url)
            return None
        finally:
            await self._polite_sleep()
            await self._pages.put(page)
