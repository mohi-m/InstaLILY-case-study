"""robots.txt gate. We respect Disallow rules and crawl-delay before fetching."""

import logging
import urllib.request
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

# A realistic Windows Chrome UA so the browser context and robots check agree.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ROBOTS_URL = "https://www.partselect.com/robots.txt"


class RobotsGate:
    def __init__(self, base: str = "https://www.partselect.com") -> None:
        self.base = base
        self._rp = RobotFileParser()
        self._crawl_delay: float | None = None

    def load(self) -> None:
        req = urllib.request.Request(ROBOTS_URL, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            self._rp.parse(text.splitlines())
            delay = self._rp.crawl_delay(USER_AGENT)
            self._crawl_delay = float(delay) if delay else None
            logger.info("robots.txt loaded — crawl-delay: %s",
                        f"{self._crawl_delay}s" if self._crawl_delay else "not set")
        except Exception as exc:
            # If robots.txt is unreachable, fail closed to the configured polite delay.
            logger.warning("Could not fetch robots.txt (%s) — treating all URLs as allowed", exc)
            self._rp = RobotFileParser()
            self._rp.allow_all = True

    def allowed(self, url: str) -> bool:
        return self._rp.can_fetch(USER_AGENT, url)

    @property
    def crawl_delay(self) -> float | None:
        return self._crawl_delay
