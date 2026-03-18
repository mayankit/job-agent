"""
generic.py

Generic fallback ATS handler. Uses form_filler.py directly on any page.
Works for any ATS platform not explicitly listed.
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


class GenericHandler(BaseATSHandler):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return True  # Always matches as the final fallback

    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        """Attempt to detect and fill a login/register form generically."""
        logger.info("Generic handler: attempting login/register")
        try:
            # Check for email + password fields (login form)
            email_input = page.locator("input[type=email], input[name*=email]").first
            pw_input = page.locator("input[type=password]").first

            if await email_input.count() > 0 and await pw_input.count() > 0:
                await email_input.fill(profile.get("email", ""))
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await pw_input.fill(password)
                await asyncio.sleep(random.uniform(0.3, 0.8))

                submit = page.locator("button[type=submit], input[type=submit]").first
                if await submit.count() > 0:
                    await submit.click()
                    await asyncio.sleep(random.uniform(2, 4))
                    return True
        except Exception as exc:
            logger.debug("Generic login error: %s", exc)
        return False

    async def fill_application(
        self,
        page: Page,
        profile: dict[str, Any],
        cover_letter: str,
        resume_path: str,
        evidence_folder: Path,
    ) -> bool:
        """Fill application using the generic form filler across all form steps."""
        form_data_log: list[dict] = []
        step = 3

        for form_step in range(1, 20):
            await self._screenshot(
                page,
                evidence_store.screenshot_path(evidence_folder, step, f"form_{form_step}"),
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

            submit_btn = await form_filler.detect_submit_button(page)
            if submit_btn:
                evidence_store.save_form_data(
                    evidence_folder, form_data_log, platform="generic"
                )
                await asyncio.sleep(random.uniform(
                    config.ACTION_DELAY_MIN,
                    config.ACTION_DELAY_MAX,
                ))
                await submit_btn.click()
                await asyncio.sleep(random.uniform(3, 5))
                await self._screenshot(
                    page,
                    evidence_store.screenshot_path(evidence_folder, 99, "confirmation"),
                )
                return True

            advanced = await form_filler.click_next_button(page)
            if not advanced:
                break
            await asyncio.sleep(random.uniform(1.5, 3))

        return False
