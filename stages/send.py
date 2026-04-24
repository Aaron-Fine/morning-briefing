"""Stage: send — Deliver the rendered HTML digest via SMTP.

Inputs:  html (str)
Outputs: send_result (dict: {success: bool, timestamp: str})

On failure, attempts to send a plain-text failure notification email.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from utils.time import artifact_date, format_display_date, iso_now_local, now_local

log = logging.getLogger(__name__)


def _send_digest(html: str, config: dict) -> bool:
    """Send the rendered HTML digest via SMTP.

    Returns True on success, False on failure.
    """
    delivery = config.get("delivery", {})
    smtp_host = delivery.get("smtp_host", "smtp.gmail.com")
    smtp_port = delivery.get("smtp_port", 587)
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    to_addr = delivery.get("to_address", "")
    from_name = delivery.get("from_name", "Morning Digest")

    if not smtp_user or not smtp_pass:
        log.error("SMTP_USER or SMTP_PASSWORD not set")
        return False

    if not to_addr:
        log.error("delivery.to_address not set in config/")
        return False

    subject_template = delivery.get("subject_template", "Morning Digest — {date}")
    subject = subject_template.format(date=format_display_date())

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{smtp_user}>"
    msg["To"] = to_addr

    # Plain text fallback
    plain = "Your Morning Digest is ready. View this email in an HTML-capable client."
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_addr], msg.as_string())

        log.info(f"Digest sent to {to_addr}")
        return True

    except Exception as e:
        log.error(f"Failed to send digest: {e}")
        return False


def _send_failure_notification(config: dict) -> None:
    """Send a plain-text alert when the main digest delivery fails."""
    delivery = config.get("delivery", {})
    smtp_host = delivery.get("smtp_host", "smtp.gmail.com")
    smtp_port = delivery.get("smtp_port", 587)
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    to_addr = delivery.get("to_address", "")

    if not smtp_user or not smtp_pass or not to_addr:
        log.error("Cannot send failure notification — SMTP credentials or to_address missing")
        return

    now = now_local()
    body = (
        f"Morning Digest failed to send on {format_display_date(now)}.\n\n"
        "Check the container logs for details:\n"
        "  docker compose logs morning-digest\n"
    )
    msg = MIMEText(body, "plain")
    msg["Subject"] = f"[Morning Digest] Delivery failed — {artifact_date()}"
    msg["From"] = f"Morning Digest <{smtp_user}>"
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_addr], msg.as_string())
        log.info("Failure notification sent")
    except Exception as e:
        log.error(f"Failed to send failure notification: {e}")


def run(context: dict, config: dict, model_config: dict | None = None, **kwargs) -> dict:
    """Send the digest email and return send_result artifact."""
    html = context.get("html", "")

    if not html:
        log.error("send: no HTML content to send")
        return {
            "send_result": {
                "success": False,
                "timestamp": iso_now_local(),
                "error": "no html",
            }
        }

    success = _send_digest(html, config)
    timestamp = iso_now_local()

    if success:
        log.info("=== Digest sent successfully ===")
    else:
        log.error("=== Digest send FAILED ===")
        _send_failure_notification(config)

    return {"send_result": {"success": success, "timestamp": timestamp}}
