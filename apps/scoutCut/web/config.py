"""
Application configuration — loaded once at startup from environment / .env file.

Override any constant in your shell or .env:
    APP_BASE_FEE_PER_LINK=50 uvicorn web.main:app
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # ignore unrelated env vars
        case_sensitive=False,
    )

    # ── Pricing constants (ALL values are in NIS — the absolute base currency) ──
    # ScoutCut charges per source video link and per extracted clip.
    app_base_fee_per_link: float = 40.0    # NIS — base setup fee per unique URL
    app_fee_per_clip:      float = 4.0     # NIS — per timecode / extracted clip

    # Used in the "hybrid" value-comparison model:
    #   • traditional_cost   = links × TRADITIONAL_EDITOR_RATE
    #   • hybrid_total_cost  = pure_app_revenue + FIXED_FINAL_EDIT_FEE
    traditional_editor_rate: float = 300.0  # NIS/video — industry day-rate baseline
    fixed_final_edit_fee:    float = 300.0  # NIS — one-time final polish fee

    # ── Volume discount on ScoutCut processing fee ───────────────────────────
    # discount % = number_of_links × APP_DISCOUNT_PCT_PER_LINK, capped at max.
    # e.g. defaults: 1 game=10%, 2 games=20%, 3 games=30%, 5+ games=50% (cap)
    app_discount_pct_per_link: int = 10   # percentage points added per unique URL
    app_max_discount_pct:      int = 50   # hard cap (50% = 5 games)

    # ── Currency & localisation ───────────────────────────────────────────────
    usd_to_nis_exchange_rate: float = 3.70  # divide NIS values by this to get USD
    default_language:         str   = "en"  # "en" | "he"
    default_currency:         str   = "USD" # "USD" | "NIS"


# Module-level singleton — import `settings` everywhere else
settings = Settings()
