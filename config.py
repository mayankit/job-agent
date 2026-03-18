"""
Runtime configuration — all paths derived from project root.
Zero hardcoded user data. Everything flows from profile.json at runtime.
"""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR           = Path(__file__).parent
MY_DOCS_DIR        = BASE_DIR / "my_documents"
RESUME_DIR         = MY_DOCS_DIR / "resume"
STORIES_DIR        = MY_DOCS_DIR / "stories"
PROFILE_JSON       = MY_DOCS_DIR / "profile.json"
SEARCH_CONFIG_JSON = MY_DOCS_DIR / "search_config.json"
APPLICATIONS_DIR   = BASE_DIR / "applications"
LEVEL_CACHE_JSON   = BASE_DIR / "level_cache.json"
PASSWORDS_FILE     = BASE_DIR / "passwords.enc"
DB_PATH            = BASE_DIR / "applications.db"
LOG_FILE           = BASE_DIR / "run.log"
DASHBOARD_PORT     = 8080

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
ENCRYPTION_KEY     = os.getenv("ENCRYPTION_KEY", "")

# Safety limits
MAX_APPLICATIONS_PER_RUN    = int(os.getenv("MAX_APPS_PER_RUN", "20"))
ACTION_DELAY_MIN            = float(os.getenv("ACTION_DELAY_MIN", "2.0"))
ACTION_DELAY_MAX            = float(os.getenv("ACTION_DELAY_MAX", "5.0"))
SKIP_IF_APPLIED_WITHIN_DAYS = int(os.getenv("SKIP_APPLIED_DAYS", "90"))

# Claude model — use the latest capable model
CLAUDE_MODEL = "claude-sonnet-4-6"


def load_profile() -> dict:
    if not PROFILE_JSON.exists():
        raise FileNotFoundError(
            "Profile not found. Run: python main.py --setup"
        )
    import json
    return json.loads(PROFILE_JSON.read_text())


def load_search_config() -> dict:
    if not SEARCH_CONFIG_JSON.exists():
        raise FileNotFoundError(
            "Search config not found. Run: python main.py --setup"
        )
    import json
    return json.loads(SEARCH_CONFIG_JSON.read_text())


def ensure_dirs() -> None:
    """Create required directories if they don't exist."""
    for d in [MY_DOCS_DIR, RESUME_DIR, STORIES_DIR, APPLICATIONS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
