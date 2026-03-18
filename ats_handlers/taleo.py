"""
taleo.py — Oracle Taleo ATS handler
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


class TaleoHandler(BaseATSHandler):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return "taleo.net" in url or "oraclecloud.com" in url

    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        logger.info("Taleo: attempting login/register")
        try:
            new_user = page.locator(
                "a:has-text('New User'), button:has-text('New User'), a:has-text('Create Account')"
            ).first
            sign_in = page.locator(
                "a:has-text('Sign In'), input[type=submit][value*='Sign']"
            ).first

            if await sign_in.count() > 0:
                await sign_in.click()
                await asyncio.sleep(random.uniform(1, 2))
                email = page.locator("input[name*=Email], input[type=email]").first
                pw = page.locator("input[type=password]").first
                if await email.count() > 0:
                    await email.fill(profile.get("email", ""))
                    await pw.fill(password)
                    submit = page.locator("input[type=submit], button[type=submit]").first
                    await submit.click()
                    await asyncio.sleep(random.uniform(3, 5))
                    return True
            elif await new_user.count() > 0:
                await new_user.click()
                await asyncio.sleep(random.uniform(2, 3))
                await form_filler.fill_form(page, profile)
                submit = page.locator("input[type=submit], button[type=submit]").first
                if await submit.count() > 0:
                    await submit.click()
                    await asyncio.sleep(random.uniform(3, 5))
        except Exception as exc:
            logger.warning("Taleo login error: %s", exc)
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

        for form_step in range(1, 20):
            await self._screenshot(
                page, evidence_store.screenshot_path(evidence_folder, step, f"taleo_{form_step}")
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
                "input[value*='Submit'], button:has-text('Submit')"
            ).first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                evidence_store.save_form_data(evidence_folder, form_data_log, "taleo")
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await submit_btn.click()
                await asyncio.sleep(random.uniform(3, 5))
                await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, 99, "confirmation"))
                return True

            next_btn = page.locator(
                "input[value*='Next'], a:has-text('Next'), button:has-text('Next')"
            ).first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await next_btn.click()
                await asyncio.sleep(random.uniform(2, 3))
            else:
                break

        return False
