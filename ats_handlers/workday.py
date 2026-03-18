"""
workday.py — Workday ATS handler
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


class WorkdayHandler(BaseATSHandler):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return "myworkdayjobs.com" in url or "workday.com" in url

    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        logger.info("Workday: login/register")
        try:
            # Check if sign-in form is present
            sign_in = page.locator("[data-automation-id='signInButton'], button:has-text('Sign In')").first
            if await sign_in.count() > 0:
                await sign_in.click()
                await asyncio.sleep(random.uniform(1, 2))

            email_input = page.locator("[data-automation-id='email'], input[type=email]").first
            if await email_input.count() > 0:
                await email_input.fill(profile.get("email", ""))
                await asyncio.sleep(0.5)

                pw = page.locator("[data-automation-id='password'], input[type=password]").first
                if await pw.count() > 0:
                    await pw.fill(password)
                    await asyncio.sleep(0.5)
                    submit = page.locator("[data-automation-id='signInSubmitButton'], button[type=submit]").first
                    if await submit.count() > 0:
                        await submit.click()
                        await asyncio.sleep(random.uniform(3, 5))
                        return True

            # If no sign-in, try creating an account
            create = page.locator("button:has-text('Create Account'), a:has-text('Create Account')").first
            if await create.count() > 0:
                await create.click()
                await asyncio.sleep(random.uniform(2, 3))
                await form_filler.fill_form(page, profile)
                submit = page.locator("button[type=submit]").first
                if await submit.count() > 0:
                    await submit.click()
                    await asyncio.sleep(random.uniform(3, 5))

        except Exception as exc:
            logger.warning("Workday login error: %s", exc)
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

        # Click Apply button
        try:
            apply_btn = page.locator(
                "[data-automation-id='applyNowButton'], button:has-text('Apply')"
            ).first
            if await apply_btn.count() > 0:
                await apply_btn.click()
                await asyncio.sleep(random.uniform(2, 3))
        except Exception as exc:
            logger.debug("Workday apply button: %s", exc)

        for form_step in range(1, 15):
            await self._screenshot(
                page,
                evidence_store.screenshot_path(evidence_folder, step, f"workday_{form_step}"),
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
                "[data-automation-id='bottomNavigationSubmitButton'], button:has-text('Submit')"
            ).first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                evidence_store.save_form_data(evidence_folder, form_data_log, "workday")
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await submit_btn.click()
                await asyncio.sleep(random.uniform(3, 5))
                await self._screenshot(page, evidence_store.screenshot_path(evidence_folder, 99, "confirmation"))
                return True

            next_btn = page.locator(
                "[data-automation-id='bottomNavigationNextButton'], button:has-text('Next')"
            ).first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                await asyncio.sleep(random.uniform(config.ACTION_DELAY_MIN, config.ACTION_DELAY_MAX))
                await next_btn.click()
                await asyncio.sleep(random.uniform(2, 3))
            else:
                break

        return False
