"""Central configuration loaded from environment / .env file.

Importing this module loads .env (if present) and exposes a single ``settings``
object the rest of the app reads from. Nothing here raises on missing secrets —
the app must run on mock data with no credentials at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = the directory that contains this file's parent (utils/..).
ROOT_DIR = Path(__file__).resolve().parent.parent

# Load .env from the project root if it exists. Real env vars take precedence.
load_dotenv(ROOT_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_bool(name: str, default: bool = False) -> bool:
    raw = _get(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


def _names(raw: str) -> list[str]:
    return [n.strip() for n in raw.split(",") if n.strip()]


@dataclass(frozen=True)
class Settings:
    # Plaid
    plaid_client_id: str = field(default_factory=lambda: _get("PLAID_CLIENT_ID"))
    plaid_secret: str = field(default_factory=lambda: _get("PLAID_SECRET"))
    plaid_env: str = field(default_factory=lambda: _get("PLAID_ENV", "sandbox"))

    # Anthropic
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(
        default_factory=lambda: _get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    )

    # App
    user_names: list[str] = field(default_factory=lambda: _names(_get("USER_NAME")))
    db_path: str = field(default_factory=lambda: _get("DB_PATH", "finance.db"))
    use_mock_data: bool = field(default_factory=lambda: _get_bool("USE_MOCK_DATA", True))

    @property
    def db_file(self) -> Path:
        """Absolute path to the SQLite file (relative paths resolve to root)."""
        p = Path(self.db_path)
        return p if p.is_absolute() else ROOT_DIR / p

    @property
    def has_plaid(self) -> bool:
        return bool(self.plaid_client_id and self.plaid_secret)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
