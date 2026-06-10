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

    # ── Pricing constants ─────────────────────────────────────────────────────
    # ScoutCut charges per source video link and per extracted clip.
    app_base_fee_per_link: float = 40.0   # USD — base setup fee per unique URL
    app_fee_per_clip:      float = 4.0    # USD — per timecode / extracted clip

    # Used in the "hybrid" value-comparison model:
    #   • traditional_cost   = links × TRADITIONAL_EDITOR_RATE
    #   • hybrid_total_cost  = pure_app_revenue + FIXED_FINAL_EDIT_FEE
    traditional_editor_rate: float = 300.0   # USD/video — industry day-rate baseline
    fixed_final_edit_fee:    float = 300.0   # USD — one-time final polish fee


# Module-level singleton — import `settings` everywhere else
settings = Settings()
