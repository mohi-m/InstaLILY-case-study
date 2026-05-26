import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
# Make backend's `app` package and the sibling `scraper` package importable.
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scraper"))
