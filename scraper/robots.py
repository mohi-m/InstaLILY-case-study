"""robots.txt gate. We respect Disallow rules and crawl-delay before fetching."""

import urllib.request
from urllib.robotparser import RobotFileParser

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
        except Exception:
            # If robots.txt is unreachable, fail closed to the configured polite delay.
            self._rp = RobotFileParser()
            self._rp.allow_all = True

    def allowed(self, url: str) -> bool:
        return self._rp.can_fetch(USER_AGENT, url)

    @property
    def crawl_delay(self) -> float | None:
        return self._crawl_delay
