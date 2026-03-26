"""Send the digest email via SMTP."""

import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

log = logging.getLogger(__name__)


def send_digest(html: str, config: dict) -> bool:
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
        log.error("delivery.to_address not set in config.yaml")
        return False

    subject_template = delivery.get("subject_template", "Morning Digest — {date}")
    subject = subject_template.format(date=datetime.now().strftime("%A, %B %-d, %Y"))

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
