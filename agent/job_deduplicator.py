"""
job_deduplicator.py

Cross-portal job deduplication.

The same real job posting can appear on multiple portals (LinkedIn, Indeed, Dice,
Wellfound) with different portal-assigned IDs. Without deduplication the agent
would apply to the same role multiple times.

Strategy
────────
1. Canonical fingerprint: normalize (company, title) → 16-char hex key.
   - Strips legal suffixes (Inc, LLC, Corp…), punctuation, and whitespace.
   - Expands common abbreviations (Sr→Senior, Prin→Principal, Eng→Engineer).
   - Case-insensitive, whitespace-collapsed.

2. Within-session dedup: before the apply loop, deduplicate the collected job
   list by canonical key. When two listings share a key, keep the one with the
   highest priority (Easy Apply > LinkedIn external > other portals).

3. Cross-session dedup: application_tracker stores canonical_key alongside
   job_id. Before starting any work on a job, check BOTH identifiers so that
   a role applied via LinkedIn won't be re-applied via Indeed the next day.

Portal priority (higher = prefer this listing when merging duplicates):
  linkedin easy_apply  → 3
  linkedin external    → 2
  other portals        → 1
"""

import hashlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Normalisation helpers ──────────────────────────────────────────────────────

_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|corp|corporation|ltd|limited|"
    r"co|company|companies|group|holdings|international|technologies|"
    r"solutions|services|systems|enterprises|ventures|labs|studio|studios"
    r")\b\.?",
    re.IGNORECASE,
)

_TITLE_EXPANSIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsr\.?\b",    re.I), "senior"),
    (re.compile(r"\bjr\.?\b",    re.I), "junior"),
    (re.compile(r"\bprin\.?\b",  re.I), "principal"),
    (re.compile(r"\bmgr\.?\b",   re.I), "manager"),
    (re.compile(r"\beng\.?\b",   re.I), "engineer"),
    (re.compile(r"\bdev\.?\b",   re.I), "developer"),
    (re.compile(r"\barch\.?\b",  re.I), "architect"),
    (re.compile(r"\bdir\.?\b",   re.I), "director"),
    (re.compile(r"\bvp\b",       re.I), "vice president"),
    (re.compile(r"\bswe\b",      re.I), "software engineer"),
    (re.compile(r"\bsde\b",      re.I), "software development engineer"),
    (re.compile(r"\bml\b",       re.I), "machine learning"),
    (re.compile(r"\bai\b",       re.I), "artificial intelligence"),
]

_NON_WORD = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")


def _normalize_company(name: str) -> str:
    name = name.lower().strip()
    name = _LEGAL_SUFFIXES.sub(" ", name)
    name = _NON_WORD.sub(" ", name)
    return _WHITESPACE.sub(" ", name).strip()


def _normalize_title(title: str) -> str:
    title = title.lower().strip()
    for pattern, replacement in _TITLE_EXPANSIONS:
        title = pattern.sub(replacement, title)
    title = _NON_WORD.sub(" ", title)
    return _WHITESPACE.sub(" ", title).strip()


def canonical_key(company: str, title: str) -> str:
    """
    Return a 16-char hex fingerprint for a (company, title) pair.
    Two jobs are considered the same real posting if their canonical keys match.
    """
    co = _normalize_company(company)
    ti = _normalize_title(title)
    raw = f"{co}::{ti}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# ── Portal priority ────────────────────────────────────────────────────────────

def _portal_priority(job: dict[str, Any]) -> int:
    """Higher is better — prefer Easy Apply, then LinkedIn, then others."""
    if job.get("is_easy_apply"):
        return 3
    portal = job.get("portal", "").lower()
    if portal == "linkedin" or "linkedin" in job.get("apply_url", ""):
        return 2
    return 1


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove duplicate job postings across portals.

    For each canonical key, keep the listing with the highest portal priority
    (Easy Apply > LinkedIn external > everything else).

    Annotates each surviving job with '_canonical_key' for use by the tracker.
    """
    seen: dict[str, dict[str, Any]] = {}          # canonical_key → best job so far
    dropped: list[tuple[str, str, str]] = []      # (company, title, portal) of dropped dupes

    for job in jobs:
        key = canonical_key(
            job.get("company", ""),
            job.get("title", ""),
        )
        job = dict(job)           # don't mutate caller's dict
        job["_canonical_key"] = key

        if key not in seen:
            seen[key] = job
        else:
            existing = seen[key]
            if _portal_priority(job) > _portal_priority(existing):
                dropped.append((
                    existing.get("company", ""),
                    existing.get("title", ""),
                    existing.get("portal", existing.get("apply_url", "unknown")),
                ))
                seen[key] = job
            else:
                dropped.append((
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("portal", job.get("apply_url", "unknown")),
                ))

    if dropped:
        logger.info(
            "Deduplicator removed %d duplicate listing(s) across portals:", len(dropped)
        )
        for company, title, source in dropped[:10]:
            logger.info("  dropped: %s — %s (from %s)", company, title, source)
        if len(dropped) > 10:
            logger.info("  … and %d more", len(dropped) - 10)

    result = list(seen.values())
    logger.info(
        "After dedup: %d unique jobs (from %d total listings, %d duplicates removed)",
        len(result), len(jobs), len(jobs) - len(result),
    )
    return result


def explain_duplicate(job_a: dict[str, Any], job_b: dict[str, Any]) -> str:
    """Return a human-readable explanation of why two jobs are considered duplicates."""
    ka = canonical_key(job_a.get("company", ""), job_a.get("title", ""))
    kb = canonical_key(job_b.get("company", ""), job_b.get("title", ""))
    co_a = _normalize_company(job_a.get("company", ""))
    co_b = _normalize_company(job_b.get("company", ""))
    ti_a = _normalize_title(job_a.get("title", ""))
    ti_b = _normalize_title(job_b.get("title", ""))
    match = "YES" if ka == kb else "NO"
    return (
        f"Duplicate: {match}\n"
        f"  A  company='{co_a}'  title='{ti_a}'  key={ka}\n"
        f"  B  company='{co_b}'  title='{ti_b}'  key={kb}"
    )
