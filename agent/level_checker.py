"""
level_checker.py

Validates that a job's seniority is equivalent to the user's target level
by checking levels.fyi. Caches results for 7 days.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

_CACHE_TTL_DAYS = 7
_FALLBACK_SENIOR_PATTERNS = re.compile(
    r"\b(principal|staff|senior staff|distinguished|fellow|architect|director)\b",
    re.IGNORECASE,
)


def _load_cache() -> dict[str, Any]:
    if not config.LEVEL_CACHE_JSON.exists():
        return {}
    try:
        return json.loads(config.LEVEL_CACHE_JSON.read_text())
    except Exception:
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    config.LEVEL_CACHE_JSON.write_text(json.dumps(data, indent=2))


def _cache_key(company: str, job_title: str) -> str:
    return f"{company.lower().strip()}::{job_title.lower().strip()}"


def _is_cache_fresh(entry: dict[str, Any]) -> bool:
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"])
        return datetime.now(timezone.utc) - cached_at < timedelta(days=_CACHE_TTL_DAYS)
    except Exception:
        return False


def _scrape_levels_fyi(company: str) -> list[dict[str, Any]]:
    """Scrape levels.fyi company page for level/TC data."""
    slug = company.lower().replace(" ", "").replace(".", "").replace(",", "")
    url = f"https://www.levels.fyi/companies/{slug}/levels/"
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            logger.debug("levels.fyi returned %d for %s", resp.status_code, company)
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        levels = []
        for row in soup.select("tr, [data-level]"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                title_text = cells[0].get_text(strip=True)
                tc_text = cells[-1].get_text(strip=True).replace(",", "").replace("$", "").replace("K", "000")
                try:
                    tc = int(re.sub(r"[^\d]", "", tc_text))
                    levels.append({"title": title_text, "tc": tc})
                except ValueError:
                    pass
        return levels
    except Exception as exc:
        logger.debug("levels.fyi scrape error for %s: %s", company, exc)
        return []


def _tc_for_title(levels_data: list[dict], job_title: str) -> int | None:
    """Find the TC for the best-matching level."""
    title_lower = job_title.lower()
    # Exact match
    for lvl in levels_data:
        if lvl["title"].lower() == title_lower:
            return lvl["tc"]
    # Partial match
    for lvl in levels_data:
        if any(word in lvl["title"].lower() for word in title_lower.split()):
            return lvl["tc"]
    return None


async def is_at_target_level(
    company: str,
    job_title: str,
    target_level_desc: str,
    min_tc: int,
) -> tuple[bool, int]:
    """
    Returns (passes_filter, estimated_tc).
    passes_filter=True means this job is at or above the target level/TC.
    """
    key = _cache_key(company, job_title)
    cache = _load_cache()

    if key in cache and _is_cache_fresh(cache[key]):
        entry = cache[key]
        logger.debug("Level cache hit: %s", key)
        return entry["passes"], entry["estimated_tc"]

    # Check title patterns as quick fallback
    title_matches = bool(_FALLBACK_SENIOR_PATTERNS.search(job_title))

    levels_data = _scrape_levels_fyi(company)
    estimated_tc = 0

    if levels_data:
        tc = _tc_for_title(levels_data, job_title)
        if tc:
            estimated_tc = tc
            passes = tc >= min_tc
        else:
            passes = title_matches
    else:
        passes = title_matches
        estimated_tc = min_tc if title_matches else 0

    result = {
        "passes": passes,
        "estimated_tc": estimated_tc,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    cache[key] = result
    _save_cache(cache)

    logger.info(
        "Level check: %s / %s → passes=%s, est_tc=%d",
        company, job_title, passes, estimated_tc,
    )
    return passes, estimated_tc
