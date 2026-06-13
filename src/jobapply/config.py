"""Configuration loading: environment (.env) + preferences.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (src/jobapply/config.py -> project root)
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
BROWSER_PROFILE_DIR = ROOT / "browser_profiles"
OUTPUT_DIR = ROOT / "output"


class Settings(BaseSettings):
    """Secrets & environment, loaded from .env."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field(default="claude-opus-4-8", alias="CLAUDE_MODEL")
    database_url: str = Field(default=f"sqlite:///{DATA_DIR / 'jobs.db'}", alias="DATABASE_URL")


# ---- preferences.yaml schema ----

class Filters(BaseModel):
    locations: list[str] = []
    remote_ok: bool = True
    min_salary_lpa: Optional[float] = None
    experience_years: Optional[int] = None
    exclude_keywords: list[str] = []
    posted_within_days: int = 30


class PlatformConfig(BaseModel):
    enabled: bool = True
    easy_apply_only: bool = False
    max_results: int = 50
    use_recommended: bool = False   # LinkedIn: scrape the profile-matched "Recommended" feed
                                     # instead of (or before) keyword search


class Ranking(BaseModel):
    min_score_to_show: int = 60
    auto_tailor_top_n: int = 10


class ApplyConfig(BaseModel):
    mode: str = "assist"   # "assist" | "manual"
    daily_limit: int = 20


class Preferences(BaseModel):
    titles: list[str] = []
    keywords: list[str] = []
    filters: Filters = Filters()
    platforms: dict[str, PlatformConfig] = {}
    ranking: Ranking = Ranking()
    apply: ApplyConfig = ApplyConfig()


def load_preferences(path: Optional[Path] = None) -> Preferences:
    """Load config/preferences.yaml (falls back to the .example for first run)."""
    path = path or (CONFIG_DIR / "preferences.yaml")
    if not path.exists():
        example = CONFIG_DIR / "preferences.example.yaml"
        if example.exists():
            raise FileNotFoundError(
                f"{path} not found. Copy {example.name} to preferences.yaml and edit it."
            )
        raise FileNotFoundError(f"{path} not found.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Preferences.model_validate(data)


def ensure_dirs() -> None:
    """Create runtime directories if missing."""
    for d in (DATA_DIR, BROWSER_PROFILE_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)


settings = Settings()
