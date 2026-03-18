"""
greenhouse.py — Greenhouse ATS handler
"""
import asyncio
import logging
import random
from pathlib import Path
from typing import Any

from playwright.async_api import Page

import config
from ats_handlers.base import BaseATSHandler
from agent import form_filler, evidence_store

logger = logging.getLogger(__name__)


class GreenhouseHandler(BaseATSHandler):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return "greenhouse.io" in url or "boards.greenhouse" in url

    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        # Greenhouse typically doesn't require login for applications
        logger.info("Greenhouse: no login required for most applications")
        return True

    async def fill_application(
        self,
        page: Page,
        profile: dict[str, Any],
        cover_letter: str,
        resume_path: str,
        evidence_folder: Path,
    ) -> bool:
        form_data_log: list[dict] = []
        step = 3

        await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, step, "greenhouse_form"))
        step += 1

        # Greenhouse uses a single-page form
        await form_filler.fill_form(
            page=page,
            profile=profile,
            cover_letter=cover_letter,
            resume_path=resume_path,
            form_data_log=form_data_log,
        )
        await asyncio.sleep(random.uniform(2, 3))

        # Handle cover letter textarea specifically
        try:
            cl_textarea = page.locator("textarea[name*=cover], #cover_letter, [id*=cover_letter]").first
            if await cl_textarea.count() > 0 and await cl_textarea.is_visible():
                await cl_textarea.fill(cover_letter)
                form_data_log.append({"field_label": "Cover Letter", "value": cover_letter[:100] + "..."})
        except Exception as exc:
            logger.debug("Greenhouse cover letter: %s", exc)

        await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, step, "before_submit"))
        step += 1

        submit_btn = page.locator("input[type=submit][value*='Submit'], button:has-text('Submit Application')").first
        if await submit_btn.count() > 0 and await submit_btn.is_visible():
            evidence_store.save_form_data(evidence_folder, form_data_log, "greenhouse")
            await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
            await submit_btn.click()
            await asyncio.sleep(random.uniform(3, 5))
            await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, 99, "confirmation"))
            return True

        return False
