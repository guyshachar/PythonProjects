"""
ScoutCut pricing engine.

All monetary constants are read from web.config.Settings so they can be
overridden via environment variables without touching code.

Pricing model
─────────────
traditional_cost   = number_of_links × TRADITIONAL_EDITOR_RATE
pure_app_revenue   = (number_of_links × APP_BASE_FEE_PER_LINK)
                   + (total_clips     × APP_FEE_PER_CLIP)
hybrid_total_cost  = pure_app_revenue + FIXED_FINAL_EDIT_FEE
client_savings     = traditional_cost − hybrid_total_cost
"""

from web.config import settings
from web.models import JobQuoteRequest


def calculate_job_price(req: JobQuoteRequest) -> dict:
    """
    Compute the full pricing breakdown from a quote request.

    Returns a dict that matches JobQuoteResponse field-for-field.
    """
    number_of_links = len({row.url for row in req.video_rows})
    total_clips     = sum(len(row.timecodes) for row in req.video_rows)

    # ── Core formulas ─────────────────────────────────────────────────────────
    traditional_cost  = number_of_links * settings.traditional_editor_rate
    pure_app_revenue  = (
        number_of_links * settings.app_base_fee_per_link
        + total_clips   * settings.app_fee_per_clip
    )
    hybrid_total_cost = pure_app_revenue + settings.fixed_final_edit_fee
    client_savings    = traditional_cost - hybrid_total_cost
    savings_pct       = (
        round(client_savings / traditional_cost * 100, 1)
        if traditional_cost > 0 else 0.0
    )

    return {
        # ── Input counts ──────────────────────────────────────────────────────
        "number_of_links": number_of_links,
        "total_clips":     total_clips,

        # ── Financial breakdown ───────────────────────────────────────────────
        "traditional_cost":   round(traditional_cost,  2),
        "pure_app_revenue":   round(pure_app_revenue,  2),
        "fixed_final_edit_fee": round(settings.fixed_final_edit_fee, 2),
        "hybrid_total_cost":  round(hybrid_total_cost, 2),
        "client_savings":     round(client_savings,    2),
        "savings_percentage": savings_pct,

        # ── Config snapshot (so the frontend can render formula details) ──────
        "rate_per_link": settings.app_base_fee_per_link,
        "rate_per_clip": settings.app_fee_per_clip,
        "traditional_rate": settings.traditional_editor_rate,
    }
