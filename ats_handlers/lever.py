"""
lever.py — Lever ATS handler
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


class LeverHandler(BaseATSHandler):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return "lever.co" in url or "jobs.lever.co" in url

    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        # Lever applications are typically no-login
        logger.info("Lever: no login required")
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

        await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, step, "lever_form"))
        step += 1

        await form_filler.fill_form(
            page=page,
            profile=profile,
            cover_letter=cover_letter,
            resume_path=resume_path,
            form_data_log=form_data_log,
        )
        await asyncio.sleep(random.uniform(1, 2))

        # Lever cover letter
        try:
            cl_area = page.locator("textarea[name*=comments], .lever-field textarea").first
            if await cl_area.count() > 0 and await cl_area.is_visible():
                await cl_area.fill(cover_letter)
                form_data_log.append({"field_label": "Cover Letter / Additional Info", "value": cover_letter[:100] + "..."})
        except Exception as exc:
            logger.debug("Lever cover letter: %s", exc)

        await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, step, "before_submit"))
        step += 1

        submit_btn = page.locator("button[type=submit]:has-text('Submit'), .template-btn-submit").first
        if await submit_btn.count() > 0 and await submit_btn.is_visible():
            evidence_store.save_form_data(evidence_folder, form_data_log, "lever")
            await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
            await submit_btn.click()
            await asyncio.sleep(random.uniform(3, 5))
            await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, 99, "confirmation"))
            return True

        return False
