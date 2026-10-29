"""Outgoing email. With no provider configured it only logs, and says so (demo mode)."""
import logging
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger("gppsl.mail")


async def send_email(to: str, subject: str, body: str) -> dict[str, Any]:
    """Returns {"status": "sent"|"demo-logged"|"failed", "provider": ...}. Never raises."""
    s = get_settings()
    try:
        if s.resend_api_key:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {s.resend_api_key}"},
                    json={"from": s.mail_from, "to": [to], "subject": subject, "text": body},
                )
                r.raise_for_status()
            return {"status": "sent", "provider": "resend"}
        if s.brevo_api_key:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": s.brevo_api_key},
                    json={"sender": {"email": s.mail_from}, "to": [{"email": to}],
                          "subject": subject, "textContent": body},
                )
                r.raise_for_status()
            return {"status": "sent", "provider": "brevo"}
        if s.smtp_host:
            import aiosmtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = s.mail_from, to, subject
            msg.set_content(body)
            await aiosmtplib.send(msg, hostname=s.smtp_host, port=s.smtp_port,
                                  username=s.smtp_user or None, password=s.smtp_password or None,
                                  start_tls=True)
            return {"status": "sent", "provider": "smtp"}
    except Exception as exc:  # noqa: BLE001 - email must never break a business action
        logger.warning("Email to %s failed: %s", to, exc)
        return {"status": "failed", "provider": "error", "error": str(exc)}
    logger.info("[DEMO MODE - email not actually sent] to=%s subject=%s", to, subject)
    return {"status": "demo-logged", "provider": "none (no email keys configured)"}
