from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

Interval = str  # "1d" | "1h" | "1m"
Market = str  # "cn" | "us" | "hk"
Action = str  # "buy" | "hold" | "sell"


def project_root() -> Path:
    env = os.environ.get("QUANT_PICKER_ROOT")
    if env:
        return Path(env)
    # src/quant_picker/config.py -> project root
    return Path(__file__).resolve().parents[2]


@lru_cache
def load_settings() -> dict[str, Any]:
    path = project_root() / "config" / "settings.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_strategies_config() -> dict[str, Any]:
    path = project_root() / "config" / "strategies.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_screener_config() -> dict[str, Any]:
    path = project_root() / "config" / "screener.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_env() -> None:
    root = project_root()
    for candidate in (root / ".env", root / "config" / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            return
    load_dotenv(root / "config" / ".env.example", override=False)


def clear_settings_cache() -> None:
    load_settings.cache_clear()
    load_strategies_config.cache_clear()
    load_screener_config.cache_clear()


def save_notification_flags(*, email_enabled: bool, wpush_enabled: bool) -> None:
    """Update notification channel toggles in settings.yaml."""
    import re

    path = project_root() / "config" / "settings.yaml"
    content = path.read_text(encoding="utf-8")
    content = re.sub(
        r"^(\s*)email_enabled:\s*\S+",
        rf"\1email_enabled: {str(email_enabled).lower()}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r"^(\s*)wechat_enabled:\s*\S+",
        rf"\1wechat_enabled: {str(wpush_enabled).lower()}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(content, encoding="utf-8")
    clear_settings_cache()


def db_path() -> Path:
    settings = load_settings()
    rel = settings.get("database", {}).get("path", "data/quant_picker.db")
    path = project_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    """Resolve SQLAlchemy URL: DATABASE_URL env > settings.database.url > SQLite file."""
    load_env()
    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url:
        return env_url
    settings = load_settings()
    cfg_url = (settings.get("database", {}) or {}).get("url", "")
    if cfg_url:
        return str(cfg_url).strip()
    return f"sqlite:///{db_path()}"


def database_schema() -> str:
    """PostgreSQL schema for project tables; ignored for SQLite."""
    settings = load_settings()
    return str((settings.get("database", {}) or {}).get("schema", "quant_picker"))


def auto_sync_intervals() -> list[str]:
    """Intervals updated by background scheduler; default daily only."""
    intervals = (load_settings().get("scheduler", {}) or {}).get("auto_sync_intervals")
    if intervals:
        return [str(x) for x in intervals]
    return ["1d"]


def market_daily_run_schedule() -> dict[str, dict[str, str]]:
    """Per-market post-close daily job time (Asia/Shanghai) and cron weekdays."""
    sched = (load_settings().get("scheduler", {}) or {})
    custom = sched.get("market_daily_run")
    if custom:
        return {str(k).lower(): dict(v) for k, v in custom.items()}
    legacy = sched.get("daily_run_time", "15:35")
    return {
        "cn": {"time": legacy, "days": "mon-fri"},
        "hk": {"time": "16:35", "days": "mon-fri"},
        "us": {"time": "09:00", "days": "mon-sat"},
    }


def uses_postgresql() -> bool:
    return database_url().startswith("postgresql")
