"""
ScoutCut pricing engine.

NIS is the absolute base currency. All intermediate calculations are
performed in NIS, then optionally converted to USD and rounded to the
nearest whole integer.

Volume discount (applied to ScoutCut processing fee only):
    discount_pct   = min(number_of_links × APP_DISCOUNT_PCT_PER_LINK,
                         APP_MAX_DISCOUNT_PCT)
    1 game → 10%   2 games → 20%   3 games → 30%   5+ games → 50% (cap)

Pricing model (NIS, post-discount):
    gross_app_revenue     = (links × BASE_FEE_PER_LINK) + (clips × FEE_PER_CLIP)
    volume_discount_amount = gross_app_revenue × discount_pct / 100
    pure_app_revenue      = gross_app_revenue − volume_discount_amount
    hybrid_total_cost     = pure_app_revenue + FIXED_FINAL_EDIT_FEE
    traditional_cost      = links × TRADITIONAL_EDITOR_RATE
    client_savings        = traditional_cost − hybrid_total_cost
"""

from web.config import settings
from web.models import JobQuoteRequest

_SYMBOLS = {"USD": "$", "NIS": "₪"}


def _to_display(nis_value: float, currency: str) -> int:
    """Convert a NIS amount to the requested currency and round to integer."""
    if currency == "USD":
        return round(nis_value / settings.usd_to_nis_exchange_rate)
    return round(nis_value)


def calculate_job_price(req: JobQuoteRequest) -> dict:
    """
    Full pricing breakdown.  Returns a dict matching JobQuoteResponse.
    """
    currency = (req.currency or settings.default_currency).upper()

    # ── Step 1: Raw counts ─────────────────────────────────────────────────────
    number_of_links = len({row.url for row in req.video_rows})
    total_clips     = sum(len(row.timecodes) for row in req.video_rows)

    # ── Step 2: NIS base calculations ─────────────────────────────────────────
    traditional_cost_nis   = number_of_links * settings.traditional_editor_rate
    gross_app_revenue_nis  = (
        number_of_links * settings.app_base_fee_per_link
        + total_clips   * settings.app_fee_per_clip
    )

    # ── Step 3: Volume discount on processing fee ──────────────────────────────
    discount_pct    = min(
        number_of_links * settings.app_discount_pct_per_link,
        settings.app_max_discount_pct,
    )
    discount_nis    = gross_app_revenue_nis * discount_pct / 100
    pure_app_revenue_nis  = gross_app_revenue_nis - discount_nis

    # ── Step 4: Totals ─────────────────────────────────────────────────────────
    hybrid_total_cost_nis  = pure_app_revenue_nis + settings.fixed_final_edit_fee
    client_savings_nis     = traditional_cost_nis - hybrid_total_cost_nis

    # ── Step 5: Convert + strict integer rounding ──────────────────────────────
    traditional_cost       = _to_display(traditional_cost_nis,     currency)
    gross_app_revenue      = _to_display(gross_app_revenue_nis,    currency)
    volume_discount_amount = _to_display(discount_nis,             currency)
    pure_app_revenue       = _to_display(pure_app_revenue_nis,     currency)
    fixed_final_edit_fee   = _to_display(settings.fixed_final_edit_fee, currency)
    hybrid_total_cost      = _to_display(hybrid_total_cost_nis,    currency)
    client_savings         = _to_display(client_savings_nis,       currency)

    rate_per_link          = _to_display(settings.app_base_fee_per_link,   currency)
    rate_per_clip          = _to_display(settings.app_fee_per_clip,        currency)
    traditional_rate       = _to_display(settings.traditional_editor_rate, currency)

    savings_pct = (
        round(client_savings_nis / traditional_cost_nis * 100, 1)
        if traditional_cost_nis > 0 else 0.0
    )

    return {
        # Counts
        "number_of_links":       number_of_links,
        "total_clips":           total_clips,

        # Localisation
        "currency":              currency,
        "currency_symbol":       _SYMBOLS.get(currency, currency),

        # Volume discount
        "volume_discount_pct":    discount_pct,          # e.g. 30
        "volume_discount_amount": volume_discount_amount, # absolute, display currency

        # Financial breakdown (post-discount, rounded integers)
        "gross_app_revenue":     gross_app_revenue,      # before discount
        "pure_app_revenue":      pure_app_revenue,        # after discount
        "fixed_final_edit_fee":  fixed_final_edit_fee,
        "hybrid_total_cost":     hybrid_total_cost,
        "traditional_cost":      traditional_cost,
        "client_savings":        client_savings,
        "savings_percentage":    savings_pct,

        # UI formula helpers
        "rate_per_link":         rate_per_link,
        "rate_per_clip":         rate_per_clip,
        "traditional_rate":      traditional_rate,
    }
