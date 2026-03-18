"""
evidence_store.py

Creates and manages per-application evidence folders.
Every application produces a self-contained evidence folder. No exceptions.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


def create_evidence_folder(
    company: str,
    job_id: str,
    metadata: dict[str, Any],
) -> Path:
    """
    Create evidence folder at applications/{Company}/{YYYY-MM-DD_HHMMSS}_{job_id}/
    Writes initial metadata.json immediately.
    Returns the folder path.
    """
    safe_company = _safe_name(company)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_job_id = _safe_name(job_id)
    folder = config.APPLICATIONS_DIR / safe_company / f"{ts}_{safe_job_id}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "screenshots").mkdir(exist_ok=True)

    # Write initial metadata immediately (before any browser interaction)
    write_metadata(folder, metadata)
    logger.info("Evidence folder created: %s", folder)
    return folder


def write_metadata(folder: Path, metadata: dict[str, Any]) -> None:
    path = folder / "metadata.json"
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))


def read_metadata(folder: Path) -> dict[str, Any]:
    path = folder / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def update_metadata(folder: Path, updates: dict[str, Any]) -> None:
    data = read_metadata(folder)
    data.update(updates)
    write_metadata(folder, data)


def save_cover_letter(folder: Path, text: str) -> None:
    (folder / "cover_letter.md").write_text(text, encoding="utf-8")
    (folder / "cover_letter.txt").write_text(text, encoding="utf-8")


def save_job_description(folder: Path, text: str) -> None:
    (folder / "job_description.txt").write_text(text, encoding="utf-8")


def save_company_research(folder: Path, text: str) -> None:
    (folder / "company_research.txt").write_text(text, encoding="utf-8")


def save_form_data(
    folder: Path,
    fields: list[dict[str, Any]],
    platform: str = "unknown",
) -> None:
    payload = {
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "fields": fields,
    }
    (folder / "form_data.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False)
    )


def screenshot_path(folder: Path, step: int, label: str = "") -> Path:
    """Return the path for the Nth screenshot."""
    safe_label = _safe_name(label)[:40] if label else ""
    name = f"{step:02d}_{safe_label}.png" if safe_label else f"{step:02d}.png"
    return folder / "screenshots" / name


def error_screenshot_path(folder: Path) -> Path:
    return folder / "screenshots" / "error.png"


def setup_app_logger(folder: Path) -> logging.FileHandler:
    """Attach a per-application log file handler."""
    log_path = folder / "run.log"
    handler = logging.FileHandler(str(log_path))
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(handler)
    return handler


def build_initial_metadata(
    job_id: str,
    job_title: str,
    company: str,
    location: str,
    job_url: str,
    application_type: str,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "job_title": job_title,
        "company": company,
        "location": location,
        "job_url": job_url,
        "external_url": None,
        "application_type": application_type,
        "ats_platform": None,
        "status": "pending",
        "failure_reason": None,
        "levels_verified": False,
        "estimated_tc": 0,
        "domain_score": 0,
        "applied_at": None,
        "new_account_created": False,
        "cover_letter_path": "cover_letter.md",
        "form_data_path": "form_data.json",
        "screenshots": [],
    }


def _safe_name(s: str) -> str:
    """Convert a string to a filesystem-safe name."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s).strip("_.")[:80]
