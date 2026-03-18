"""
password_manager.py

Fernet-encrypted storage for portal passwords.
The master password is NEVER written to logs, screenshots, DB, or form_data.json.
"""
import json
import logging
import os
import secrets
import string
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

import config

logger = logging.getLogger(__name__)

_PASSWORDS_FILE = config.PASSWORDS_FILE


def _get_fernet() -> Fernet:
    """Load Fernet key from .env. Raises if missing."""
    key = config.ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY not set. Run: python main.py --setup to generate one."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def generate_master_password(length: int = 24) -> str:
    """Generate a strong random master password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_encryption_key() -> str:
    """Generate a new Fernet key. Call this once during --setup."""
    return Fernet.generate_key().decode()


def store_password(site_key: str, password: str) -> None:
    """Encrypt and persist a password for the given site key."""
    f = _get_fernet()
    data = _load_store()
    data[site_key] = f.encrypt(password.encode()).decode()
    _save_store(data)
    logger.info("Password stored for: %s", site_key)


def retrieve_password(site_key: str) -> str | None:
    """Decrypt and return the stored password, or None if not found."""
    f = _get_fernet()
    data = _load_store()
    token = data.get(site_key)
    if token is None:
        return None
    return f.decrypt(token.encode()).decode()


def list_sites() -> list[str]:
    """Return all site keys that have stored passwords."""
    return list(_load_store().keys())


def store_master(master_password: str) -> None:
    """Store the master password under the special '__master__' key."""
    store_password("__master__", master_password)


def get_master() -> str | None:
    """Retrieve the master password."""
    return retrieve_password("__master__")


def _load_store() -> dict[str, str]:
    if not _PASSWORDS_FILE.exists():
        return {}
    raw = _PASSWORDS_FILE.read_text()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _save_store(data: dict[str, str]) -> None:
    _PASSWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PASSWORDS_FILE.write_text(json.dumps(data, indent=2))
