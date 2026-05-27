"""robots.txt gate. We respect Disallow rules and crawl-delay before fetching."""

import logging
import urllib.request
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ROBOTS_URL = "https://www.partselect.com/robots.txt"


class RobotsGate:
    def __init__(self, base: str = "https://www.partselect.com") -> None:
        self.base = base
        self._rp = RobotFileParser()
        self._crawl_delay: float | None = None

    def load(self) -> None:
        # Use the same User-Agent for the robots.txt request as for page fetches
        # so that any agent-specific rules apply correctly.
        req = urllib.request.Request(ROBOTS_URL, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            self._rp.parse(text.splitlines())
            delay = self._rp.crawl_delay(USER_AGENT)
            self._crawl_delay = float(delay) if delay else None
            log.info("robots.txt loaded; crawl-delay=%s", self._crawl_delay)
        except Exception as exc:
            # Fail permissive: treat all paths as allowed but honour our own polite delay.
            log.warning("Could not fetch robots.txt (%s); defaulting to allow-all", exc)
            self._rp = RobotFileParser()
            self._rp.allow_all = True

    def allowed(self, url: str) -> bool:
        result = self._rp.can_fetch(USER_AGENT, url)
        if not result:
            log.debug("robots.txt disallows %s", url)
        return result

    @property
    def crawl_delay(self) -> float | None:
        return self._crawl_delay
