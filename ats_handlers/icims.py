"""
icims.py — iCIMS ATS handler
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


class ICIMSHandler(BaseATSHandler):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return "icims.com" in url

    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        logger.info("iCIMS: attempting login/register")
        try:
            # Look for sign-in or create account
            sign_in = page.locator("a:has-text('Sign In'), button:has-text('Sign In')").first
            create = page.locator("a:has-text('Create Account'), button:has-text('Register')").first

            if await sign_in.count() > 0:
                await sign_in.click()
                await asyncio.sleep(random.uniform(2, 3))

                email = page.locator("input[name*=email], input[type=email]").first
                pw = page.locator("input[type=password]").first

                if await email.count() > 0:
                    await email.fill(profile.get("email", ""))
                    await pw.fill(password)
                    await asyncio.sleep(0.5)
                    submit = page.locator("input[type=submit], button[type=submit]").first
                    await submit.click()
                    await asyncio.sleep(random.uniform(2, 4))
                    return True

            elif await create.count() > 0:
                await create.click()
                await asyncio.sleep(random.uniform(2, 3))
                await form_filler.fill_form(page, profile)
                submit = page.locator("input[type=submit], button[type=submit]").first
                if await submit.count() > 0:
                    await submit.click()
                    await asyncio.sleep(random.uniform(3, 5))

        except Exception as exc:
            logger.warning("iCIMS login error: %s", exc)
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
                page, evidence_store.screenshot_path(evidence_folder, step, f"icims_{form_step}")
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
                "input[value*='Submit'], button:has-text('Submit Application')"
            ).first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                evidence_store.save_form_data(evidence_folder, form_data_log, "icims")
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await submit_btn.click()
                await asyncio.sleep(random.uniform(3, 5))
                await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, 99, "confirmation"))
                return True

            next_btn = page.locator("input[value*='Next'], button:has-text('Next')").first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await next_btn.click()
                await asyncio.sleep(random.uniform(2, 3))
            else:
                break

        return False
