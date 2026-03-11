"""
Email delivery via Resend API.
Falls back to saving HTML to file if RESEND_API_KEY is not configured.
"""
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from sentinel.config import RESEND_API_KEY, RESEND_FROM_EMAIL, RESEND_TO_EMAIL, LOGS_DIR

logger = logging.getLogger(__name__)


def send_email(html: str, subject: Optional[str] = None) -> bool:
    """
    Sends the HTML email. Returns True on success.
    If RESEND_API_KEY is not set, saves to file instead.
    """
    today = date.today().isoformat()
    subject = subject or f"Sentinel Daily Radar — {today}"

    if not RESEND_API_KEY:
        return _save_to_file(html, today)

    if not RESEND_TO_EMAIL:
        logger.warning("RESEND_TO_EMAIL not set. Saving email to file.")
        return _save_to_file(html, today)

    try:
        import resend
        resend.api_key = RESEND_API_KEY

        params = {
            "from":    RESEND_FROM_EMAIL,
            "to":      [RESEND_TO_EMAIL],
            "subject": subject,
            "html":    html,
        }
        email_resp = resend.Emails.send(params)
        logger.info("Email sent via Resend: id=%s to=%s", email_resp.get("id"), RESEND_TO_EMAIL)
        # Also save a copy locally
        _save_to_file(html, today)
        return True

    except Exception as exc:
        logger.error("Resend send error: %s — saving to file instead.", exc)
        return _save_to_file(html, today)


def _save_to_file(html: str, date_str: str) -> bool:
    """Saves the HTML email to logs/ directory for manual review."""
    try:
        sent_dir = LOGS_DIR / "emails"
        sent_dir.mkdir(parents=True, exist_ok=True)
        output_path = sent_dir / f"sentinel_{date_str}.html"
        output_path.write_text(html, encoding="utf-8")
        logger.info("Email saved to: %s", output_path)
        return True
    except Exception as exc:
        logger.error("Failed to save email file: %s", exc)
        return False


