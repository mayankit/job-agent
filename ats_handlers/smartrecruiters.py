"""
smartrecruiters.py — SmartRecruiters ATS handler
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


class SmartRecruitersHandler(BaseATSHandler):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return "smartrecruiters.com" in url or "jobs.smartrecruiters.com" in url

    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        logger.info("SmartRecruiters: attempting login/register")
        try:
            # SmartRecruiters may prompt to sign in via social or email
            email_btn = page.locator("button:has-text('Continue with email'), a:has-text('email')").first
            if await email_btn.count() > 0:
                await email_btn.click()
                await asyncio.sleep(random.uniform(1, 2))

            email = page.locator("input[type=email], input[name*=email]").first
            if await email.count() > 0:
                await email.fill(profile.get("email", ""))
                cont = page.locator("button:has-text('Continue'), button[type=submit]").first
                if await cont.count() > 0:
                    await cont.click()
                    await asyncio.sleep(random.uniform(1, 2))

            pw = page.locator("input[type=password]").first
            if await pw.count() > 0:
                await pw.fill(password)
                submit = page.locator("button[type=submit], button:has-text('Sign in')").first
                if await submit.count() > 0:
                    await submit.click()
                    await asyncio.sleep(random.uniform(3, 5))
                    return True
        except Exception as exc:
            logger.warning("SmartRecruiters login error: %s", exc)
        return False

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

        for form_step in range(1, 15):
            await self._screenshot(
                page, evidence_store.screenshot_path(evidence_folder, step, f"sr_{form_step}")
            )
            step += 1

            await form_filler.fill_form(
                page=page,
                profile=profile,
                cover_letter=cover_letter,
                resume_path=resume_path,
                form_data_log=form_data_log,
            )
            await asyncio.sleep(random.uniform(1, 2))

            submit_btn = page.locator(
                "button[data-test*=submit], button:has-text('Send Application'), button:has-text('Submit')"
            ).first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                evidence_store.save_form_data(evidence_folder, form_data_log, "smartrecruiters")
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await submit_btn.click()
                await asyncio.sleep(random.uniform(3, 5))
                await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, 99, "confirmation"))
                return True

            next_btn = page.locator(
                "button[data-test*=next], button:has-text('Next'), button:has-text('Continue')"
            ).first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await next_btn.click()
                await asyncio.sleep(random.uniform(2, 3))
            else:
                break

        return False
