"""
ScoutCut pricing engine.

NIS is the absolute base currency. All intermediate calculations are
performed in NIS, then optionally converted to USD and rounded to the
nearest whole integer before being returned.

Strict rounding contract (per spec):
    14.7 → 15   |   14.2 → 14   |   0.5 → 0 (Python banker's rounding — fine for display)

Exchange rate and base fees are read from web.config.Settings so they can
be overridden via environment variables without touching code.

Pricing model (NIS):
    traditional_cost  = links × TRADITIONAL_EDITOR_RATE
    pure_app_revenue  = (links × APP_BASE_FEE_PER_LINK) + (clips × APP_FEE_PER_CLIP)
    hybrid_total_cost = pure_app_revenue + FIXED_FINAL_EDIT_FEE
    client_savings    = traditional_cost − hybrid_total_cost
"""

from web.config import settings
from web.models import JobQuoteRequest

_SYMBOLS = {"USD": "$", "NIS": "₪"}


def _to_display(nis_value: float, currency: str) -> int:
    """Convert a NIS value to the requested currency and round to integer."""
    if currency == "USD":
        return round(nis_value / settings.usd_to_nis_exchange_rate)
    return round(nis_value)


def calculate_job_price(req: JobQuoteRequest) -> dict:
    """
    Compute the full pricing breakdown from a quote request.

    All maths happen in NIS; output is rounded integers in the requested currency.
    Returns a dict that matches JobQuoteResponse field-for-field.
    """
    currency = (req.currency or settings.default_currency).upper()

    # ── Step 1: Raw counts ─────────────────────────────────────────────────────
    number_of_links = len({row.url for row in req.video_rows})
    total_clips     = sum(len(row.timecodes) for row in req.video_rows)

    # ── Step 2: NIS base calculations ─────────────────────────────────────────
    traditional_cost_nis  = number_of_links * settings.traditional_editor_rate
    pure_app_revenue_nis  = (
        number_of_links * settings.app_base_fee_per_link
        + total_clips   * settings.app_fee_per_clip
    )
    hybrid_total_cost_nis = pure_app_revenue_nis + settings.fixed_final_edit_fee
    client_savings_nis    = traditional_cost_nis - hybrid_total_cost_nis

    # ── Step 3: Convert + strict integer rounding ──────────────────────────────
    traditional_cost  = _to_display(traditional_cost_nis,  currency)
    pure_app_revenue  = _to_display(pure_app_revenue_nis,  currency)
    hybrid_total_cost = _to_display(hybrid_total_cost_nis, currency)
    client_savings    = _to_display(client_savings_nis,    currency)

    # Config constants (also rounded for UI formula display)
    fixed_final_edit_fee = _to_display(settings.fixed_final_edit_fee,    currency)
    rate_per_link        = _to_display(settings.app_base_fee_per_link,   currency)
    rate_per_clip        = _to_display(settings.app_fee_per_clip,        currency)
    traditional_rate     = _to_display(settings.traditional_editor_rate, currency)

    savings_pct = (
        round(client_savings_nis / traditional_cost_nis * 100, 1)
        if traditional_cost_nis > 0 else 0.0
    )

    return {
        # ── Counts ────────────────────────────────────────────────────────────
        "number_of_links": number_of_links,
        "total_clips":     total_clips,

        # ── Localisation metadata ──────────────────────────────────────────────
        "currency":        currency,
        "currency_symbol": _SYMBOLS.get(currency, currency),

        # ── Financial breakdown (rounded integers in requested currency) ───────
        "traditional_cost":     traditional_cost,
        "pure_app_revenue":     pure_app_revenue,
        "fixed_final_edit_fee": fixed_final_edit_fee,
        "hybrid_total_cost":    hybrid_total_cost,
        "client_savings":       client_savings,
        "savings_percentage":   savings_pct,

        # ── Config snapshot for formula display in UI ──────────────────────────
        "rate_per_link":    rate_per_link,
        "rate_per_clip":    rate_per_clip,
        "traditional_rate": traditional_rate,
    }
