"""
base.py

Abstract base class that all ATS handlers must implement.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from playwright.async_api import Page


class BaseATSHandler(ABC):

    @classmethod
    def matches_url(cls, url: str) -> bool:
        """Return True if this handler recognizes the current URL."""
        return False

    @abstractmethod
    async def login_or_register(
        self,
        page: Page,
        profile: dict[str, Any],
        password: str,
    ) -> bool:
        """
        Log in if account exists, else create a new account.
        Returns True if authenticated successfully.
        """

    @abstractmethod
    async def fill_application(
        self,
        page: Page,
        profile: dict[str, Any],
        cover_letter: str,
        resume_path: str,
        evidence_folder: Path,
    ) -> bool:
        """
        Fill and submit the application.
        Saves screenshots + form_data to evidence_folder.
        Returns True on successful submission.
        """

    async def _screenshot(self, page: Page, path: Path) -> None:
        try:
            await page.screenshot(path=str(path), full_page=False)
        except Exception:
            pass
