"""
application_runner.py

Orchestrates Easy Apply (LinkedIn) and external portal flows.
This is the main application execution engine.
"""
import asyncio
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Page

import config
from agent import evidence_store, form_filler, application_tracker

logger = logging.getLogger(__name__)

_EASY_APPLY_MAX_STEPS = 15


async def _screenshot(page: Page, path: Path) -> None:
    try:
        await page.screenshot(path=str(path), full_page=False)
    except Exception as exc:
        logger.debug("Screenshot failed: %s", exc)


async def run_easy_apply(
    page: Page,
    job: dict[str, Any],
    profile: dict[str, Any],
    cover_letter: str,
    resume_path: str,
    folder: Path,
    dry_run: bool = False,
) -> bool:
    """
    Execute LinkedIn Easy Apply flow.
    Returns True on successful submission.
    """
    logger.info("Starting Easy Apply: %s / %s", job["company"], job["job_id"])

    form_data_log: list[dict] = []
    step = 1

    try:
        # Navigate to job listing
        await page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(2, 3))

        await _screenshot(page, evidence_store.screenshot_path(folder, step, "job_listing"))
        evidence_store.update_metadata(folder, {
            "screenshots": [str(evidence_store.screenshot_path(folder, step, "job_listing"))]
        })
        step += 1

        if dry_run:
            logger.info("[DRY RUN] Would click Easy Apply — stopping here")
            evidence_store.update_metadata(folder, {"status": "dry_run"})
            return True

        # Click Easy Apply button
        ea_btn = page.locator(
            "button:has-text('Easy Apply'), .jobs-apply-button, [data-control-name='jobdetails_topcard_inapply']"
        ).first
        if not await ea_btn.is_visible():
            logger.warning("Easy Apply button not found for %s", job["job_id"])
            return False

        await asyncio.sleep(random.uniform(1, 2))
        await ea_btn.click()
        await asyncio.sleep(random.uniform(2, 3))

        # Step through multi-page form
        for form_step in range(1, _EASY_APPLY_MAX_STEPS + 1):
            await _screenshot(
                page,
                evidence_store.screenshot_path(folder, step, f"form_step_{form_step}"),
            )
            step += 1

            # Fill current form page
            await form_filler.fill_form(
                page=page,
                profile=profile,
                cover_letter=cover_letter,
                resume_path=resume_path,
                form_data_log=form_data_log,
            )
            await asyncio.sleep(random.uniform(1, 2))

            # Check for submit button
            submit_btn = await form_filler.detect_submit_button(page)
            if submit_btn:
                # Save form data BEFORE clicking submit
                evidence_store.save_form_data(folder, form_data_log, platform="linkedin_easy_apply")
                application_tracker.upsert_application({
                    "job_id": job["job_id"],
                    "company": job["company"],
                    "job_title": job["title"],
                    "location": job.get("location", ""),
                    "job_url": job["apply_url"],
                    "application_type": "easy_apply",
                    "status": "submitting",
                })

                await asyncio.sleep(random.uniform(
                    config.ACTION_DELAY_MIN,
                    config.ACTION_DELAY_MAX,
                ))
                await submit_btn.click()
                await asyncio.sleep(random.uniform(3, 5))

                # Confirmation screenshot
                await _screenshot(page, evidence_store.screenshot_path(folder, 99, "confirmation"))

                evidence_store.update_metadata(folder, {
                    "status": "applied",
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                })
                application_tracker.update_status(job["job_id"], "applied")
                logger.info("Applied successfully: %s / %s", job["company"], job["job_id"])
                return True

            # Click Next/Continue
            advanced = await form_filler.click_next_button(page)
            if not advanced:
                logger.warning("Could not advance form for %s — step %d", job["job_id"], form_step)
                break
            await asyncio.sleep(random.uniform(1.5, 3))

        logger.warning("Easy Apply did not complete for %s", job["job_id"])
        return False

    except Exception as exc:
        logger.error("Easy Apply error for %s: %s", job["job_id"], exc)
        await _screenshot(page, evidence_store.error_screenshot_path(folder))
        evidence_store.update_metadata(folder, {
            "status": "failed",
            "failure_reason": str(exc),
        })
        application_tracker.update_status(job["job_id"], "failed", str(exc))
        return False


async def run_external_apply(
    page: Page,
    job: dict[str, Any],
    profile: dict[str, Any],
    cover_letter: str,
    resume_path: str,
    folder: Path,
    master_password: str,
    dry_run: bool = False,
) -> bool:
    """
    Execute external ATS application flow.
    Detects ATS platform and delegates to appropriate handler.
    """
    from ats_handlers import detect_handler, get_generic_handler

    external_url = job.get("external_url", "")
    if not external_url:
        logger.warning("No external URL for job %s", job["job_id"])
        return False

    logger.info("Starting external apply: %s → %s", job["company"], external_url)

    try:
        await page.goto(external_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(2, 4))

        step = 1
        await _screenshot(page, evidence_store.screenshot_path(folder, step, "external_landing"))
        step += 1

        if dry_run:
            logger.info("[DRY RUN] Would fill external ATS form — stopping here")
            evidence_store.update_metadata(folder, {"status": "dry_run"})
            return True

        # Detect ATS platform
        handler = detect_handler(page.url)
        ats_name = handler.__class__.__name__.replace("Handler", "").lower()
        evidence_store.update_metadata(folder, {"ats_platform": ats_name})
        logger.info("ATS platform detected: %s", ats_name)

        # Login / register
        logged_in = await handler.login_or_register(page, profile, master_password)
        new_account = not logged_in  # If login failed we might have created one
        evidence_store.update_metadata(folder, {"new_account_created": new_account})

        await _screenshot(page, evidence_store.screenshot_path(folder, step, "after_login"))
        step += 1

        # Fill and submit
        form_data_log: list[dict] = []
        success = await handler.fill_application(
            page=page,
            profile=profile,
            cover_letter=cover_letter,
            resume_path=resume_path,
            evidence_folder=folder,
        )

        evidence_store.save_form_data(folder, form_data_log, platform=ats_name)

        if success:
            evidence_store.update_metadata(folder, {
                "status": "applied",
                "applied_at": datetime.now(timezone.utc).isoformat(),
            })
            application_tracker.update_status(job["job_id"], "applied")
            logger.info("External apply successful: %s", job["job_id"])
        else:
            evidence_store.update_metadata(folder, {"status": "failed"})
            application_tracker.update_status(job["job_id"], "failed", "handler returned False")

        return success

    except Exception as exc:
        logger.error("External apply error for %s: %s", job["job_id"], exc)
        await _screenshot(page, evidence_store.error_screenshot_path(folder))
        evidence_store.update_metadata(folder, {
            "status": "failed",
            "failure_reason": str(exc),
        })
        application_tracker.update_status(job["job_id"], "failed", str(exc))
        return False
