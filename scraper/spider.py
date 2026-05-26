"""Scope-locked Playwright crawler for PartSelect Refrigerator/Dishwasher data.

Drives a real Chromium (with stealth) so we get past the anti-bot 403 that plain
HTTP requests hit. Concurrency is 1 with randomised polite delays. Run ONCE; the
results persist in the Postgres volume.
"""

import asyncio
import os
import random
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from parse import extract_links, parse_model_page, parse_part_page
from robots import USER_AGENT, RobotsGate

BASE = "https://www.partselect.com"
SEEDS = [f"{BASE}/Refrigerator-Models.htm", f"{BASE}/Dishwasher-Models.htm"]

MIN_DELAY = float(os.getenv("SCRAPE_MIN_DELAY", "3"))
MAX_DELAY = float(os.getenv("SCRAPE_MAX_DELAY", "7"))
MAX_MODELS = int(os.getenv("SCRAPE_MAX_MODELS", "40"))
MAX_PARTS = int(os.getenv("SCRAPE_MAX_PARTS", "200"))

CF_MARKERS = ("Just a moment", "Checking your browser", "cf-challenge")


async def _polite_sleep(robots: RobotsGate) -> None:
    delay = robots.crawl_delay or random.uniform(MIN_DELAY, MAX_DELAY)
    await asyncio.sleep(delay)


async def _fetch(page, url: str, retries: int = 3) -> str | None:
    for attempt in range(retries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            html = await page.content()
            if any(marker in html for marker in CF_MARKERS):
                await asyncio.sleep(5 * (attempt + 1))  # let challenge settle, retry
                continue
            return html
        except Exception:
            await asyncio.sleep(2 ** (attempt + 1))
    return None


async def crawl():
    """Async generator yielding ('model'|'part', record) tuples."""
    robots = RobotsGate(BASE)
    robots.load()

    seen: set[str] = set()
    brand_q: list[str] = list(SEEDS)
    model_q: list[str] = []
    part_q: list[str] = []
    models_done = parts_done = 0

    try:
        from playwright_stealth import stealth_async
    except Exception:
        stealth_async = None

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = await context.new_page()
        if stealth_async:
            await stealth_async(page)

        async def visit(url: str) -> str | None:
            if url in seen:
                return None
            seen.add(url)
            if not robots.allowed(url):
                return None
            html = await _fetch(page, url)
            await _polite_sleep(robots)
            return html

        # 1) Seed + brand index pages -> discover model & brand links.
        while brand_q:
            url = brand_q.pop(0)
            html = await visit(url)
            if not html:
                continue
            links = extract_links(html)
            for href in links["brand"]:
                brand_q.append(urljoin(BASE, href))
            for href in links["model"]:
                model_q.append(urljoin(BASE, href))

        # 2) Model pages.
        for url in model_q:
            if models_done >= MAX_MODELS:
                break
            html = await visit(url)
            if not html:
                continue
            record = parse_model_page(html, url)
            if record:
                models_done += 1
                for href in extract_links(html)["part"]:
                    part_q.append(urljoin(BASE, href))
                yield "model", record

        # 3) Part pages.
        for url in dict.fromkeys(part_q):
            if parts_done >= MAX_PARTS:
                break
            html = await visit(url)
            if not html:
                continue
            record = parse_part_page(html, url)
            if record:
                parts_done += 1
                yield "part", record

        await context.close()
        await browser.close()
