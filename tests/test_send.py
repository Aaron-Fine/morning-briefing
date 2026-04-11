"""Tests for stages/send.py — email delivery."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from stages.send import _send_digest, run, _send_failure_notification


class TestSendDigest:
    @patch("stages.send.smtplib.SMTP")
    @patch("stages.send.os.environ.get")
    def test_send_success(self, mock_env, mock_smtp_class):
        mock_env.side_effect = lambda key, default="": {
            "SMTP_USER": "user",
            "SMTP_PASSWORD": "pass",
        }.get(key, default)
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp

        config = {
            "delivery": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "to_address": "test@example.com",
                "from_name": "Morning Digest",
                "subject_template": "Morning Digest — {date}",
            }
        }
        html = "<html><body>Test</body></html>"

        result = _send_digest(html, config)
        assert result is True
        mock_smtp.sendmail.assert_called_once()

    @patch("stages.send.os.environ.get")
    def test_send_fails_without_smtp_user(self, mock_env):
        mock_env.return_value = ""
        config = {
            "delivery": {
                "smtp_host": "smtp.gmail.com",
                "to_address": "test@example.com",
            }
        }
        html = "<html>Test</html>"
        result = _send_digest(html, config)
        assert result is False

    @patch("stages.send.os.environ.get")
    def test_send_fails_without_to_address(self, mock_env):
        mock_env.side_effect = lambda key, default="": {
            "SMTP_USER": "user",
            "SMTP_PASSWORD": "pass",
        }.get(key, default)
        config = {
            "delivery": {
                "smtp_host": "smtp.gmail.com",
            }
        }
        html = "<html>Test</html>"
        result = _send_digest(html, config)
        assert result is False

    @patch("stages.send.smtplib.SMTP")
    @patch("stages.send.os.environ.get")
    def test_send_fails_on_smtp_error(self, mock_env, mock_smtp_class):
        mock_env.side_effect = lambda key, default="": {
            "SMTP_USER": "user",
            "SMTP_PASSWORD": "pass",
        }.get(key, default)
        mock_smtp_class.side_effect = Exception("Connection refused")

        config = {
            "delivery": {
                "smtp_host": "smtp.gmail.com",
                "to_address": "test@example.com",
            }
        }
        html = "<html>Test</html>"
        result = _send_digest(html, config)
        assert result is False


class TestSendFailureNotification:
    @patch("stages.send.smtplib.SMTP")
    @patch("stages.send.os.environ.get")
    def test_notification_sent(self, mock_env, mock_smtp_class):
        mock_env.side_effect = lambda key, default="": {
            "SMTP_USER": "user",
            "SMTP_PASSWORD": "pass",
        }.get(key, default)
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp

        config = {
            "delivery": {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "to_address": "test@example.com",
            }
        }
        _send_failure_notification(config)
        mock_smtp.sendmail.assert_called_once()

    @patch("stages.send.os.environ.get")
    def test_notification_skipped_without_credentials(self, mock_env):
        mock_env.return_value = ""
        config = {"delivery": {"to_address": "test@example.com"}}
        _send_failure_notification(config)


class TestSendStageRun:
    def test_run_with_no_html(self):
        context = {}
        config = {"delivery": {}}
        result = run(context, config)
        assert result["send_result"]["success"] is False
        assert "error" in result["send_result"]

    def test_run_with_empty_html(self):
        context = {"html": ""}
        config = {"delivery": {}}
        result = run(context, config)
        assert result["send_result"]["success"] is False

    @patch("stages.send._send_digest")
    @patch("stages.send._send_failure_notification")
    def test_run_with_html_success(self, mock_notify, mock_send):
        mock_send.return_value = True
        context = {"html": "<html>Test</html>"}
        config = {"delivery": {"to_address": "test@example.com"}}
        result = run(context, config)
        assert result["send_result"]["success"] is True
        assert "timestamp" in result["send_result"]
        mock_notify.assert_not_called()

    @patch("stages.send._send_digest")
    @patch("stages.send._send_failure_notification")
    def test_run_with_html_failure(self, mock_notify, mock_send):
        mock_send.return_value = False
        context = {"html": "<html>Test</html>"}
        config = {"delivery": {"to_address": "test@example.com"}}
        result = run(context, config)
        assert result["send_result"]["success"] is False
        mock_notify.assert_called_once()
