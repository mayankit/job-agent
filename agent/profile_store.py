"""
profile_store.py

Saves and loads profile.json — the runtime source of truth.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


def save_profile(
    extracted: dict[str, Any],
    search_config: dict[str, Any] | None = None,
    path: Path | None = None,
) -> Path:
    """
    Persist extracted profile data (plus optional search_config) to profile.json.
    Returns the path written.
    """
    path = path or config.PROFILE_JSON
    payload: dict[str, Any] = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "source_resume": extracted.get("_meta", {}).get("source_resume", ""),
        "source_stories": extracted.get("_meta", {}).get("source_stories", []),
        "profile": extracted.get("profile", {}),
        "stories": extracted.get("stories", []),
    }
    if search_config:
        payload["search_config"] = search_config

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("Profile saved to %s", path)
    return path


def load_profile(path: Path | None = None) -> dict[str, Any]:
    """Load profile.json. Raises FileNotFoundError if missing."""
    path = path or config.PROFILE_JSON
    if not path.exists():
        raise FileNotFoundError(
            f"Profile not found at {path}. Run: python main.py --setup"
        )
    data = json.loads(path.read_text())
    logger.debug("Profile loaded from %s", path)
    return data


def update_search_config(
    search_config: dict[str, Any],
    path: Path | None = None,
) -> None:
    """Merge new search_config into existing profile.json."""
    path = path or config.PROFILE_JSON
    data = load_profile(path)
    data["search_config"] = search_config
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Search config updated in %s", path)


def profile_exists(path: Path | None = None) -> bool:
    path = path or config.PROFILE_JSON
    return path.exists()


def get_flat_profile(path: Path | None = None) -> dict[str, Any]:
    """Return the nested 'profile' dict directly for convenience."""
    return load_profile(path).get("profile", {})


def get_stories(path: Path | None = None) -> list[dict[str, Any]]:
    """Return the list of STAR stories."""
    return load_profile(path).get("stories", [])


def get_search_config(path: Path | None = None) -> dict[str, Any]:
    """Return search_config dict."""
    data = load_profile(path)
    if "search_config" in data:
        return data["search_config"]
    # Fallback to standalone search_config.json
    sc_path = config.SEARCH_CONFIG_JSON
    if sc_path.exists():
        return json.loads(sc_path.read_text())
    raise FileNotFoundError(
        "search_config not found. Run: python main.py --setup"
    )
