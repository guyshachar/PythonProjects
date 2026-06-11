"""
Delivery notification dispatcher.

Required environment variables for email (set in .env or docker-compose):
    SMTP_HOST   e.g. smtp.gmail.com
    SMTP_PORT   e.g. 587  (STARTTLS) or 465 (SSL)
    SMTP_USER   e.g. you@gmail.com
    SMTP_PASS   app password or SMTP credential
    SMTP_FROM   sender address (defaults to SMTP_USER)

For WhatsApp (Twilio):
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_WHATSAPP_FROM   e.g. +14155238886
"""

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import List

log = logging.getLogger(__name__)


def send_delivery_notification(
    contact_method: str,
    contact: str,
    links: List[str],
    job_id: str,
    report: str = "",
) -> bool:
    links_block = "\n".join(f"  {i+1}. {url}" for i, url in enumerate(links))
    message = (
        f"Your ScoutCut highlights are ready!\n\n"
        f"Job ID: {job_id}\n\n"
        f"{'Link' if len(links) == 1 else 'Links'}:\n{links_block}\n\n"
        f"Links are available for 7 days.\n"
        f"Powered by ScoutCut"
    )
    if report:
        message += f"\n\n{report}"

    if contact_method == "email":
        return _send_email(contact, "ScoutCut: your highlights are ready", message)
    if contact_method == "whatsapp":
        return _send_whatsapp(contact, message)

    log.warning("Unknown delivery method: %s", contact_method)
    return False


# ── Email ──────────────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USER", "")
    passwd = os.getenv("SMTP_PASS", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    from_addr = os.getenv("SMTP_FROM", user)

    if not host or not user or not passwd:
        log.warning(
            "[EMAIL] SMTP not configured (SMTP_HOST/SMTP_USER/SMTP_PASS missing) — "
            "logging message instead. To: %s | Subject: %s\n%s",
            to, subject, body,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as s:
                s.login(user, passwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as s:
                s.ehlo()
                s.starttls()
                s.login(user, passwd)
                s.send_message(msg)
        log.info("[EMAIL] Sent to %s (job %s)", to, msg.get("Subject", ""))
        return True
    except Exception as exc:
        log.error("[EMAIL] Failed to send to %s: %s", to, exc)
        return False


# ── WhatsApp ───────────────────────────────────────────────────────────────────

def _send_whatsapp(to: str, message: str) -> bool:
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_ = os.getenv("TWILIO_WHATSAPP_FROM", "")

    if not sid or not token or not from_:
        log.warning(
            "[WHATSAPP] Twilio not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/WHATSAPP_FROM missing) — "
            "logging message instead. To: %s\n%s",
            to, message,
        )
        return False

    try:
        from twilio.rest import Client
        client = Client(sid, token)
        client.messages.create(
            from_=f"whatsapp:{from_}",
            body=message,
            to=f"whatsapp:{to}",
        )
        log.info("[WHATSAPP] Sent to %s", to)
        return True
    except Exception as exc:
        log.error("[WHATSAPP] Failed to send to %s: %s", to, exc)
        return False
