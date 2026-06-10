"""
Payment processor dispatcher.

Each payment method has its own handler.  In production, replace the
stub body with the real SDK call.  The function signature is identical
for all methods so the dispatcher can call them uniformly.

Environment variables used by the production stubs:
    STRIPE_SECRET_KEY          – Apple Pay / Google Pay / Credit Card (Stripe)
    BIT_API_KEY                – Bit (Israeli mobile payment)
    BIT_MERCHANT_ID
"""

import logging
import os
import uuid

from web.models import PaymentVerifyRequest, PaymentVerifyResponse

log = logging.getLogger(__name__)

# ── Dispatcher ─────────────────────────────────────────────────────────────────

def process_payment(req: PaymentVerifyRequest) -> PaymentVerifyResponse:
    """Route to the correct processor and return a unified response."""
    handlers = {
        "apple_pay":   _apple_pay,
        "google_pay":  _google_pay,
        "credit_card": _credit_card,
        "bit":         _bit,
    }
    handler = handlers.get(req.method)
    if handler is None:
        return PaymentVerifyResponse(
            success=False,
            payment_token="",
            message=f"Unknown payment method: {req.method}",
        )
    return handler(req)


# ── Apple Pay ─────────────────────────────────────────────────────────────────

def _apple_pay(req: PaymentVerifyRequest) -> PaymentVerifyResponse:
    """
    Production: complete the Apple Pay payment session via Stripe.

    TODO:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        intent = stripe.PaymentIntent.create(
            amount=int(req.amount * 100),          # Stripe uses cents
            currency=req.currency.lower(),
            payment_method_types=["card"],         # Apple Pay resolves to card
            metadata=req.metadata,
        )
        token = intent.id
    """
    log.info("[Apple Pay] mock charge %.2f %s | metadata=%s",
             req.amount, req.currency, req.metadata)
    token = str(uuid.uuid4())
    return PaymentVerifyResponse(
        success=True,
        payment_token=token,
        message=f"Apple Pay: {req.currency} {req.amount:.0f} approved.",
    )


# ── Google Pay ────────────────────────────────────────────────────────────────

def _google_pay(req: PaymentVerifyRequest) -> PaymentVerifyResponse:
    """
    Production: confirm the Google Pay payment token via Stripe.

    TODO:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        intent = stripe.PaymentIntent.confirm(req.metadata.get("payment_intent_id"))
        token = intent.id
    """
    log.info("[Google Pay] mock charge %.2f %s", req.amount, req.currency)
    token = str(uuid.uuid4())
    return PaymentVerifyResponse(
        success=True,
        payment_token=token,
        message=f"Google Pay: {req.currency} {req.amount:.0f} approved.",
    )


# ── Credit Card ───────────────────────────────────────────────────────────────

def _credit_card(req: PaymentVerifyRequest) -> PaymentVerifyResponse:
    """
    Production: charge the tokenised card via Stripe.

    The frontend should collect the card with Stripe Elements and pass
    the resulting PaymentMethod ID in req.metadata["payment_method_id"].

    TODO:
        import stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        intent = stripe.PaymentIntent.create(
            amount=int(req.amount * 100),
            currency=req.currency.lower(),
            payment_method=req.metadata.get("payment_method_id"),
            confirm=True,
        )
        token = intent.id
    """
    log.info("[Credit Card] mock charge %.2f %s", req.amount, req.currency)
    token = str(uuid.uuid4())
    return PaymentVerifyResponse(
        success=True,
        payment_token=token,
        message=f"Credit Card: {req.currency} {req.amount:.0f} approved.",
    )


# ── Bit (Israeli mobile payment) ──────────────────────────────────────────────

def _bit(req: PaymentVerifyRequest) -> PaymentVerifyResponse:
    """
    Production: initiate a Bit payment request via the Bit API.

    Bit is NIS-only; the frontend enforces this by only showing Bit when
    the user has selected NIS as the display currency.

    TODO:
        import requests as http
        api_key = os.getenv("BIT_API_KEY")
        merchant = os.getenv("BIT_MERCHANT_ID")
        resp = http.post(
            "https://api.paybit.co.il/v1/payment-requests",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "merchantId": merchant,
                "amount": req.amount,
                "currency": "ILS",
                "description": req.metadata.get("description", "ScoutCut job"),
                "phone": req.metadata.get("phone"),
            },
        )
        resp.raise_for_status()
        token = resp.json()["paymentRequestId"]
    """
    log.info("[Bit] mock charge %.2f NIS", req.amount)
    token = str(uuid.uuid4())
    return PaymentVerifyResponse(
        success=True,
        payment_token=token,
        message=f"Bit: ₪{req.amount:.0f} approved.",
    )
