"""Tests for stages/send.py — SMTP delivery and failure notification."""

import sys
import os
import smtplib
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.send import _send_digest, _send_failure_notification, run


class TestSendDigest:
    def _make_config(self):
        return {
            "delivery": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "to_address": "test@example.com",
                "from_name": "Test Digest",
                "subject_template": "Morning Digest — {date}",
            }
        }

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_successful_send(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        result = _send_digest("<html>test</html>", self._make_config())

        assert result is True
        mock_server.starttls.assert_called()
        mock_server.login.assert_called_with("user@example.com", "secret")
        mock_server.sendmail.assert_called()

    @patch.dict(os.environ, {"SMTP_USER": "", "SMTP_PASSWORD": ""})
    def test_missing_smtp_user_returns_false(self):
        result = _send_digest("<html>test</html>", self._make_config())
        assert result is False

    @patch.dict(os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": ""})
    def test_missing_smtp_password_returns_false(self):
        result = _send_digest("<html>test</html>", self._make_config())
        assert result is False

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    def test_missing_to_address_returns_false(self):
        config = {
            "delivery": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "from_name": "Test",
            }
        }
        result = _send_digest("<html>test</html>", config)
        assert result is False

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_smtp_exception_returns_false(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = smtplib.SMTPException("connection failed")

        result = _send_digest("<html>test</html>", self._make_config())

        assert result is False

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_subject_contains_date(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        _send_digest("<html>test</html>", self._make_config())

        msg = mock_server.sendmail.call_args[0][2]
        # Subject is UTF-8 Q-encoded: em dash becomes =E2=80=94
        assert "Morning_Digest_=E2=80=94" in msg

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_from_header_contains_from_name(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        _send_digest("<html>test</html>", self._make_config())

        msg = mock_server.sendmail.call_args[0][2]
        assert "From: Test Digest <user@example.com>" in msg

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_to_header_contains_recipient(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        _send_digest("<html>test</html>", self._make_config())

        msg = mock_server.sendmail.call_args[0][2]
        assert "To: test@example.com" in msg

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_email_has_plain_text_fallback(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        _send_digest("<html>test</html>", self._make_config())

        msg = mock_server.sendmail.call_args[0][2]
        assert "Your Morning Digest is ready" in msg

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_email_has_html_content(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server
        html_content = "<html><body><h1>Test Digest</h1></body></html>"

        _send_digest(html_content, self._make_config())

        msg = mock_server.sendmail.call_args[0][2]
        assert html_content in msg


class TestSendFailureNotification:
    def _make_config(self):
        return {
            "delivery": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "to_address": "test@example.com",
            }
        }

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_sends_failure_notification(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        _send_failure_notification(self._make_config())

        mock_server.starttls.assert_called()
        mock_server.login.assert_called_with("user@example.com", "secret")
        mock_server.sendmail.assert_called()

    @patch.dict(os.environ, {"SMTP_USER": "", "SMTP_PASSWORD": ""})
    def test_missing_credentials_logs_error(self, caplog):
        _send_failure_notification(self._make_config())
        assert "Cannot send failure notification" in caplog.text

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    def test_missing_to_address_logs_error(self, caplog):
        config = {"delivery": {"smtp_host": "smtp.example.com", "smtp_port": 587}}
        _send_failure_notification(config)
        assert "Cannot send failure notification" in caplog.text

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_failure_notification_has_correct_subject(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        _send_failure_notification(self._make_config())

        msg = mock_server.sendmail.call_args[0][2]
        # Subject is UTF-8 Q-encoded: [Morning Digest] Delivery failed — becomes =5BMorning...=E2=80=94
        assert "=5BMorning_Digest=5D_Delivery_failed_=E2=80=94" in msg

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_failure_notification_has_body_with_date(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        _send_failure_notification(self._make_config())

        msg = mock_server.sendmail.call_args[0][2]
        today = datetime.now().strftime("%A, %B %-d, %Y")
        assert today in msg

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send.smtplib.SMTP")
    def test_failure_notification_handles_smtp_error(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = smtplib.SMTPException("server down")

        _send_failure_notification(self._make_config())

        # Should not raise, just logs the error
        assert True


class TestSendRun:
    def _make_context(self, html="<html>test</html>"):
        return {"html": html}

    def _make_config(self):
        return {
            "delivery": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "to_address": "test@example.com",
                "from_name": "Test Digest",
                "subject_template": "Morning Digest — {date}",
            }
        }

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send._send_digest")
    def test_successful_send_returns_success(self, mock_send):
        mock_send.return_value = True

        result = run(self._make_context(), self._make_config())

        assert result["send_result"]["success"] is True
        assert "timestamp" in result["send_result"]

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send._send_digest")
    def test_failed_send_returns_failure(self, mock_send):
        mock_send.return_value = False

        result = run(self._make_context(), self._make_config())

        assert result["send_result"]["success"] is False

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send._send_failure_notification")
    @patch("stages.send._send_digest")
    def test_failed_send_triggers_notification(self, mock_send, mock_notify):
        mock_send.return_value = False

        run(self._make_context(), self._make_config())

        mock_notify.assert_called_once()

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    def test_empty_html_returns_failure(self):
        result = run({"html": ""}, self._make_config())
        assert result["send_result"]["success"] is False
        assert result["send_result"]["error"] == "no html"

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    def test_missing_html_key_returns_failure(self):
        result = run({}, self._make_config())
        assert result["send_result"]["success"] is False
        assert result["send_result"]["error"] == "no html"

    @patch.dict(
        os.environ, {"SMTP_USER": "user@example.com", "SMTP_PASSWORD": "secret"}
    )
    @patch("stages.send._send_digest")
    def test_timestamp_is_iso_format(self, mock_send):
        mock_send.return_value = True

        result = run(self._make_context(), self._make_config())

        datetime.fromisoformat(result["send_result"]["timestamp"])
