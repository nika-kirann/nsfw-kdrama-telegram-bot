"""Reads settings from environment / .env. No secrets are hardcoded."""
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    token: str
    channel_id: str | None
    admin_ids: frozenset[int]
    tz: ZoneInfo
    digest_time: str
    brand: str
    data_file: Path
    storage_backend: str
    db_channel_id: str | None
    flush_delay: float


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and fill it in.")
    channel = os.getenv("CHANNEL_ID", "").strip() or None
    admins = frozenset(int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x)
    data = Path(os.getenv("DATA_FILE", "data/series.json"))
    return Config(token, channel, admins,
                  ZoneInfo(os.getenv("TIMEZONE", "Asia/Kolkata")),
                  os.getenv("DAILY_DIGEST_TIME", "21:00"),
                  os.getenv("BRAND", "").strip() or "🔞 Spicy K-Drama",
                  data if data.is_absolute() else ROOT / data,
                  os.getenv("STORAGE_BACKEND", "local").strip().lower(),
                  os.getenv("DB_CHANNEL_ID", "").strip() or None,
                  float(os.getenv("STORAGE_FLUSH_DELAY", "3")))
