"""Configuration loading from YAML + environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class Settings:
    companies: list[dict] = field(default_factory=list)
    discord_webhook_url: str = ""
    db_path: str = "internships.db"
    verify_applyable: bool = True
    us_only: bool = True
    announce_backfill: bool = True
    max_backfill_per_run: int = 25
    max_announce_per_run: int = 0          # 0 = unlimited; set to 1 for a drip feed
    only_new_since_days: int | None = None     # ignore postings older than N days
    request_delay_seconds: float = 0.5
    discord_username: str = "Internship Radar"
    dry_run: bool = False

    @property
    def has_webhook(self) -> bool:
        return bool(self.discord_webhook_url)


def load_settings(
    config_path: str = "config.yaml",
    companies_path: str = "data/companies.yaml",
) -> Settings:
    load_dotenv()

    cfg = {}
    if Path(config_path).exists():
        cfg = yaml.safe_load(Path(config_path).read_text()) or {}

    companies = []
    # Companies can live inline in config.yaml or in a dedicated file.
    if cfg.get("companies"):
        companies = cfg["companies"]
    elif Path(companies_path).exists():
        loaded = yaml.safe_load(Path(companies_path).read_text()) or {}
        companies = loaded.get("companies", loaded if isinstance(loaded, list) else [])

    settings = Settings(
        companies=[c for c in companies if c.get("enabled", True)],
        discord_webhook_url=os.environ.get(
            "DISCORD_WEBHOOK_URL", cfg.get("discord_webhook_url", "")
        ),
        db_path=os.environ.get("DB_PATH", cfg.get("db_path", "internships.db")),
        verify_applyable=_as_bool(
            os.environ.get("VERIFY_APPLYABLE"), cfg.get("verify_applyable", True)
        ),
        us_only=_as_bool(os.environ.get("US_ONLY"), cfg.get("us_only", True)),
        announce_backfill=_as_bool(
            os.environ.get("ANNOUNCE_BACKFILL"), cfg.get("announce_backfill", True)
        ),
        max_backfill_per_run=int(
            os.environ.get("MAX_BACKFILL_PER_RUN", cfg.get("max_backfill_per_run", 25))
        ),
        max_announce_per_run=int(
            os.environ.get("MAX_ANNOUNCE_PER_RUN", cfg.get("max_announce_per_run", 0))
        ),
        only_new_since_days=_as_optional_int(
            os.environ.get("ONLY_NEW_SINCE_DAYS"), cfg.get("only_new_since_days")
        ),
        request_delay_seconds=float(
            os.environ.get("REQUEST_DELAY_SECONDS", cfg.get("request_delay_seconds", 0.5))
        ),
        discord_username=cfg.get("discord_username", "Internship Radar"),
        dry_run=_as_bool(os.environ.get("DRY_RUN"), cfg.get("dry_run", False)),
    )
    return settings


def _as_bool(env_val, default) -> bool:
    if env_val is None:
        return bool(default)
    return env_val.strip().lower() in ("1", "true", "yes", "on")


def _as_optional_int(env_val, default):
    if env_val not in (None, ""):
        return int(env_val)
    return default
