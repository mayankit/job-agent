"""
ATS handler registry.

Each handler detects its platform from the page URL and implements
login/register + form filling.
"""
from ats_handlers.base import BaseATSHandler
from ats_handlers.workday import WorkdayHandler
from ats_handlers.greenhouse import GreenhouseHandler
from ats_handlers.lever import LeverHandler
from ats_handlers.icims import ICIMSHandler
from ats_handlers.taleo import TaleoHandler
from ats_handlers.smartrecruiters import SmartRecruitersHandler
from ats_handlers.generic import GenericHandler

_HANDLERS: list[type[BaseATSHandler]] = [
    WorkdayHandler,
    GreenhouseHandler,
    LeverHandler,
    ICIMSHandler,
    TaleoHandler,
    SmartRecruitersHandler,
]


def detect_handler(url: str) -> BaseATSHandler:
    """Return the appropriate ATS handler for the given URL."""
    for handler_cls in _HANDLERS:
        if handler_cls.matches_url(url):
            return handler_cls()
    return GenericHandler()


def get_generic_handler() -> BaseATSHandler:
    return GenericHandler()


__all__ = [
    "BaseATSHandler",
    "WorkdayHandler",
    "GreenhouseHandler",
    "LeverHandler",
    "ICIMSHandler",
    "TaleoHandler",
    "SmartRecruitersHandler",
    "GenericHandler",
    "detect_handler",
    "get_generic_handler",
]
