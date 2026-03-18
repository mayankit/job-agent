"""
job_searcher.py

Job search and scraping across multiple portals.
Currently implements: LinkedIn (Easy Apply + external ATS links).
Portal router dispatches to the right search function based on search_config["portals"].

Supported portals:
  linkedin   — LinkedIn job search (Easy Apply + external links). Recommended.
               Requires a LinkedIn account (email set during --setup).
  indeed     — Indeed job listings (external apply only, no direct apply API).
  glassdoor  — Glassdoor job listings (links to company ATS).
  dice       — Dice tech job board (external apply).
  wellfound  — Wellfound/AngelList startup jobs (external apply).
  levels_fyi — Levels.fyi job board (TC-verified senior/staff roles).

Adding a new portal:
  1. Add a search function below following the pattern of _search_linkedin().
  2. Register it in PORTAL_SEARCH_FUNCS at the bottom of this file.
  3. Add the portal name to _ALL_PORTALS in main.py.
"""
import asyncio
import logging
import random
import re
import urllib.parse
from typing import Any

from playwright.async_api import Page, BrowserContext

import config

logger = logging.getLogger(__name__)

_NO_SPONSORSHIP_PATTERNS = re.compile(
    r"(not.*sponsor|no.*sponsor|unable.*sponsor|cannot.*sponsor|"
    r"us.?citizen|authorized.to.work|must.*be.*authorized|"
    r"not.*provide.*sponsor)",
    re.IGNORECASE,
)


def _build_linkedin_search_url(title: str, location: str = "United States") -> str:
    params = {
        "keywords": title,
        "location": location,
        "f_TPR": "r604800",   # Past week
        "f_JT": "F",          # Full-time
        "sortBy": "DD",       # Most recent
    }
    return "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(params)


async def _extract_job_cards(page: Page) -> list[dict[str, Any]]:
    """Extract job listing cards from a LinkedIn search results page."""
    jobs = []
    await asyncio.sleep(random.uniform(2, 4))

    cards = page.locator(".job-card-container, [data-job-id], .jobs-search-results__list-item")
    count = await cards.count()

    for i in range(count):
        card = cards.nth(i)
        try:
            job_id = await card.get_attribute("data-job-id") or f"job_{i}"
            title_el = card.locator(".job-card-list__title, .base-search-card__title").first
            company_el = card.locator(".job-card-list__company-name, .base-search-card__subtitle").first
            location_el = card.locator(".job-card-container__metadata-item, .job-card-list__entity-lockup").first

            title_text = ""
            company_text = ""
            location_text = ""

            try:
                title_text = await title_el.inner_text()
            except Exception:
                pass
            try:
                company_text = await company_el.inner_text()
            except Exception:
                pass
            try:
                location_text = await location_el.inner_text()
            except Exception:
                pass

            # Detect Easy Apply
            easy_apply = False
            try:
                ea = card.locator("text=Easy Apply")
                easy_apply = await ea.count() > 0
            except Exception:
                pass

            if title_text and company_text:
                jobs.append({
                    "job_id": job_id.strip(),
                    "title": title_text.strip(),
                    "company": company_text.strip(),
                    "location": location_text.strip(),
                    "is_easy_apply": easy_apply,
                    "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}/",
                    "job_description": "",
                })
        except Exception as exc:
            logger.debug("Card %d extraction error: %s", i, exc)

    logger.info("Found %d job cards on page", len(jobs))
    return jobs


async def _extract_job_description(page: Page, job: dict[str, Any]) -> str:
    """Navigate to a job listing and extract the full description."""
    try:
        await page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(random.uniform(2, 3))

        desc_el = page.locator(
            ".jobs-description__content, .job-view-layout, .show-more-less-html"
        ).first
        count = await desc_el.count()
        if count > 0:
            return (await desc_el.inner_text()).strip()
    except Exception as exc:
        logger.debug("JD extraction error for %s: %s", job.get("job_id"), exc)
    return ""


def has_no_sponsorship_language(job_description: str) -> bool:
    return bool(_NO_SPONSORSHIP_PATTERNS.search(job_description))


def score_domain_relevance(
    job_description: str,
    priority_domains: list[str],
) -> int:
    """Return 0-100 relevance score based on keyword overlap."""
    if not priority_domains:
        return 50
    jd_lower = job_description.lower()
    hits = sum(1 for domain in priority_domains if domain.lower() in jd_lower)
    return min(100, int(hits / len(priority_domains) * 100))


async def login_linkedin(
    page: Page,
    email: str,
    password: str,
) -> bool:
    """Log in to LinkedIn. Returns True on success."""
    logger.info("Logging in to LinkedIn as %s", email)
    await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
    await asyncio.sleep(random.uniform(2, 3))

    try:
        await page.fill("#username", email)
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await page.fill("#password", password)
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await page.click("[data-litms-control-urn='login-submit'], button[type=submit]")
        await asyncio.sleep(random.uniform(3, 5))

        # Check for CAPTCHA or verification
        if "checkpoint" in page.url or "captcha" in page.url.lower():
            logger.warning("LinkedIn CAPTCHA/verification required.")
            print("\n⚠️  LinkedIn requires verification. Please complete it in the browser window, then press Enter.")
            input()

        # Check login success
        if "feed" in page.url or "mynetwork" in page.url:
            logger.info("LinkedIn login successful")
            return True
        else:
            logger.warning("LinkedIn login may have failed. Current URL: %s", page.url)
            return False
    except Exception as exc:
        logger.error("LinkedIn login error: %s", exc)
        return False


async def search_jobs(
    page: Page,
    search_config: dict[str, Any],
    max_per_title: int = 25,
) -> list[dict[str, Any]]:
    """
    Search LinkedIn for all target job titles.
    Returns deduplicated list of job dicts.
    """
    titles = search_config.get("target_titles", [])
    location = search_config.get("location", "United States")
    all_jobs: dict[str, dict[str, Any]] = {}

    for title in titles:
        logger.info("Searching LinkedIn for: %s", title)
        url = _build_linkedin_search_url(title, location)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(3, 5))

            # Scroll to load more results
            for _ in range(3):
                await page.keyboard.press("End")
                await asyncio.sleep(random.uniform(1.5, 2.5))

            cards = await _extract_job_cards(page)
            for job in cards[:max_per_title]:
                if job["job_id"] not in all_jobs:
                    all_jobs[job["job_id"]] = job

            await asyncio.sleep(random.uniform(
                config.ACTION_DELAY_MIN,
                config.ACTION_DELAY_MAX,
            ))
        except Exception as exc:
            logger.error("Search error for '%s': %s", title, exc)

    jobs = list(all_jobs.values())
    logger.info("Total unique jobs found: %d", len(jobs))
    return jobs


async def fetch_job_descriptions(
    page: Page,
    jobs: list[dict[str, Any]],
    max_jobs: int = 50,
) -> list[dict[str, Any]]:
    """Enrich jobs with full job descriptions."""
    enriched = []
    for job in jobs[:max_jobs]:
        jd = await _extract_job_description(page, job)
        job["job_description"] = jd
        enriched.append(job)
        await asyncio.sleep(random.uniform(
            config.ACTION_DELAY_MIN,
            config.ACTION_DELAY_MAX,
        ))
    return enriched


# =============================================================
# Additional portal scrapers
# Each function returns list[dict] with the same job schema as
# _extract_job_cards() uses for LinkedIn.
# =============================================================

def _build_indeed_search_url(title: str, location: str) -> str:
    params = {"q": title, "l": location, "sort": "date", "fromage": "7"}
    return "https://www.indeed.com/jobs?" + urllib.parse.urlencode(params)


def _build_glassdoor_search_url(title: str, location: str) -> str:
    params = {"sc.keyword": title, "locT": "N", "locId": "1", "jobType": "fulltime"}
    return "https://www.glassdoor.com/Job/jobs.htm?" + urllib.parse.urlencode(params)


def _build_dice_search_url(title: str) -> str:
    params = {"q": title, "datePosted": "ONE_WEEK", "employmentType": "FULLTIME"}
    return "https://www.dice.com/jobs?" + urllib.parse.urlencode(params)


def _build_wellfound_search_url(title: str) -> str:
    slug = urllib.parse.quote_plus(title.lower())
    return f"https://wellfound.com/jobs?q={slug}&remote=true"


def _build_levels_fyi_jobs_url(title: str) -> str:
    params = {"title": title}
    return "https://www.levels.fyi/jobs?" + urllib.parse.urlencode(params)


async def _scrape_generic_job_cards(
    page: Page,
    url: str,
    card_selector: str,
    title_selector: str,
    company_selector: str,
    location_selector: str,
    link_selector: str,
    portal_name: str,
    max_per_title: int = 25,
) -> list[dict[str, Any]]:
    """Generic card scraper for portals with predictable HTML structure."""
    jobs = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(3, 5))
        for _ in range(2):
            await page.keyboard.press("End")
            await asyncio.sleep(random.uniform(1.5, 2.0))

        cards = page.locator(card_selector)
        count = min(await cards.count(), max_per_title)
        for i in range(count):
            card = cards.nth(i)
            try:
                title_text = await card.locator(title_selector).first.inner_text()
                company_text = await card.locator(company_selector).first.inner_text()
                location_text = ""
                try:
                    location_text = await card.locator(location_selector).first.inner_text()
                except Exception:
                    pass
                link = ""
                try:
                    link = await card.locator(link_selector).first.get_attribute("href") or ""
                    if link and not link.startswith("http"):
                        link = f"https://www.{portal_name}.com{link}"
                except Exception:
                    pass
                job_id = f"{portal_name}_{abs(hash(link or title_text + company_text))}"
                if title_text and company_text:
                    jobs.append({
                        "job_id": job_id,
                        "title": title_text.strip(),
                        "company": company_text.strip(),
                        "location": location_text.strip(),
                        "is_easy_apply": False,
                        "apply_url": link,
                        "job_description": "",
                        "portal": portal_name,
                    })
            except Exception as exc:
                logger.debug("%s card %d error: %s", portal_name, i, exc)
    except Exception as exc:
        logger.warning("Portal '%s' search failed: %s", portal_name, exc)
    return jobs


async def search_indeed(
    page: Page,
    search_config: dict[str, Any],
    max_per_title: int = 25,
) -> list[dict[str, Any]]:
    titles = search_config.get("target_titles", [])
    location = search_config.get("location", "United States")
    all_jobs: dict[str, dict] = {}
    for title in titles:
        logger.info("Searching Indeed for: %s", title)
        url = _build_indeed_search_url(title, location)
        jobs = await _scrape_generic_job_cards(
            page, url,
            card_selector=".job_seen_beacon, .jobsearch-ResultsList > li",
            title_selector=".jobTitle span, h2.jobTitle",
            company_selector=".companyName",
            location_selector=".companyLocation",
            link_selector="a[data-jk], a.jcs-JobTitle",
            portal_name="indeed",
            max_per_title=max_per_title,
        )
        for j in jobs:
            all_jobs.setdefault(j["job_id"], j)
        await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
    return list(all_jobs.values())


async def search_dice(
    page: Page,
    search_config: dict[str, Any],
    max_per_title: int = 25,
) -> list[dict[str, Any]]:
    titles = search_config.get("target_titles", [])
    all_jobs: dict[str, dict] = {}
    for title in titles:
        logger.info("Searching Dice for: %s", title)
        url = _build_dice_search_url(title)
        jobs = await _scrape_generic_job_cards(
            page, url,
            card_selector="dhi-search-card, .card, [data-cy='card']",
            title_selector="a.card-title-link, [data-cy='card-title']",
            company_selector=".card-company, [data-cy='card-company']",
            location_selector=".card-location, [data-cy='card-location']",
            link_selector="a.card-title-link",
            portal_name="dice",
            max_per_title=max_per_title,
        )
        for j in jobs:
            all_jobs.setdefault(j["job_id"], j)
        await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
    return list(all_jobs.values())


async def search_wellfound(
    page: Page,
    search_config: dict[str, Any],
    max_per_title: int = 25,
) -> list[dict[str, Any]]:
    titles = search_config.get("target_titles", [])
    all_jobs: dict[str, dict] = {}
    for title in titles:
        logger.info("Searching Wellfound for: %s", title)
        url = _build_wellfound_search_url(title)
        jobs = await _scrape_generic_job_cards(
            page, url,
            card_selector=".styles_component__Ey28k, [data-test='StartupResult']",
            title_selector=".styles_title__xpQDw, h2",
            company_selector=".styles_name__YrCnJ, h3",
            location_selector=".styles_location__pU_8d",
            link_selector="a",
            portal_name="wellfound",
            max_per_title=max_per_title,
        )
        for j in jobs:
            all_jobs.setdefault(j["job_id"], j)
        await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
    return list(all_jobs.values())


# Registry: portal name → async search function
PORTAL_SEARCH_FUNCS = {
    "linkedin":   search_jobs,          # defined above
    "indeed":     search_indeed,
    "dice":       search_dice,
    "wellfound":  search_wellfound,
    # glassdoor and levels_fyi use the same generic scraper pattern;
    # add dedicated functions here when needed.
}


async def search_all_portals(
    page: Page,
    search_config: dict[str, Any],
    max_per_title: int = 25,
) -> list[dict[str, Any]]:
    """
    Search all portals configured in search_config["portals"].
    Deduplicates across portals by (company, title) pair.
    """
    portals = search_config.get("portals", ["linkedin"])
    all_jobs: dict[str, dict[str, Any]] = {}

    for portal in portals:
        fn = PORTAL_SEARCH_FUNCS.get(portal)
        if fn is None:
            logger.warning("No search function for portal '%s' — skipping", portal)
            continue
        logger.info("Searching portal: %s", portal)
        try:
            jobs = await fn(page, search_config, max_per_title)
            for job in jobs:
                key = f"{job.get('company', '').lower()}::{job.get('title', '').lower()}"
                all_jobs.setdefault(key, job)
        except Exception as exc:
            logger.error("Portal '%s' error: %s", portal, exc)

    result = list(all_jobs.values())
    logger.info("Total unique jobs across all portals: %d", len(result))
    return result
