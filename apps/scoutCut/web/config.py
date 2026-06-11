"""
Application configuration — loaded once at startup.

Priority (highest → lowest):
  1. Environment variables / .env file
  2. web/config.json  (local overrides, not committed)
  3. Hard-coded defaults below

To edit pricing locally: update web/config.json.
To override in CI/production: set environment variables.
"""

import json
from pathlib import Path
from typing import Any, Tuple, Type  # noqa: UP035  (keep Tuple for 3.11 compat)

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

_CONFIG_JSON = Path(__file__).parent / "config.json"


class _JsonFileSource(PydanticBaseSettingsSource):
    """Reads web/config.json as a settings source (lower priority than env vars)."""

    def get_field_value(self, field, field_name):
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        if not _CONFIG_JSON.exists():
            return {}
        try:
            return json.loads(_CONFIG_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Pricing constants (ALL values are in NIS — the absolute base currency) ──
    app_base_fee_per_link:      float = 40.0
    app_fee_per_clip:           float = 4.0
    traditional_editor_rate:    float = 300.0
    fixed_final_edit_fee:       float = 300.0

    # ── Volume discount ───────────────────────────────────────────────────────
    app_discount_pct_per_link:  int   = 10
    app_max_discount_pct:       int   = 50

    # ── Currency & localisation ───────────────────────────────────────────────
    usd_to_nis_exchange_rate:   float = 3.70
    default_language:           str   = "en"
    default_currency:           str   = "USD"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings:   PydanticBaseSettingsSource,
        env_settings:    PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        **kwargs: Any,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # Priority: env > .env > config.json > hard-coded defaults
        # kwargs absorbs secrets_dir / file_secret_settings across pydantic-settings versions
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _JsonFileSource(settings_cls),
            *kwargs.values(),
        )


# Module-level singleton — import `settings` everywhere else
settings = Settings()
