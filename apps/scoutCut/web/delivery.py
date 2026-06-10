"""
Delivery notification dispatcher.

Production replacements are marked with # TODO comments.
Currently logs to stdout so the system works end-to-end without external deps.
"""

import logging
import os
from typing import List

log = logging.getLogger(__name__)


def send_delivery_notification(
    contact_method: str,
    contact: str,
    links: List[str],
    job_id: str,
) -> bool:
    """
    Notify the user that their job is ready.

    Args:
        contact_method: "email" or "whatsapp"
        contact:        email address or phone number (+countrycode...)
        links:          list of download/share URLs
        job_id:         job UUID (for reference)

    Returns True on success.
    """
    links_block = "\n".join(f"  {i+1}. {url}" for i, url in enumerate(links))
    message = (
        f"Your ScoutCut highlights are ready!\n\n"
        f"Job ID: {job_id}\n\n"
        f"{'Link' if len(links) == 1 else 'Links'}:\n{links_block}\n\n"
        f"Links are available for 7 days.\n"
        f"Powered by ScoutCut"
    )

    if contact_method == "email":
        return _send_email(contact, "ScoutCut: your highlights are ready", message)
    if contact_method == "whatsapp":
        return _send_whatsapp(contact, message)

    log.warning("Unknown delivery method: %s", contact_method)
    return False


# ── Email ──────────────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str) -> bool:
    """
    Send an email notification.

    TODO: Replace log with smtplib / SendGrid:

        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = os.getenv("SMTP_FROM")
        msg["To"]      = to
        msg.set_content(body)
        with smtplib.SMTP_SSL(os.getenv("SMTP_HOST"), 465) as s:
            s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"))
            s.send_message(msg)
    """
    log.info("[EMAIL] To: %s | Subject: %s\n%s", to, subject, body)
    return True


# ── WhatsApp ───────────────────────────────────────────────────────────────────

def _send_whatsapp(to: str, message: str) -> bool:
    """
    Send a WhatsApp message via Twilio.

    TODO: Replace log with Twilio:

        from twilio.rest import Client
        client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        client.messages.create(
            from_=f"whatsapp:{os.getenv('TWILIO_WHATSAPP_FROM')}",
            body=message,
            to=f"whatsapp:{to}",
        )
    """
    log.info("[WHATSAPP] To: %s\n%s", to, message)
    return True
