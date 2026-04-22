"""Tests for entrypoint.py — scheduler and cron parsing."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

from entrypoint import _parse_cron, _next_run_time


class TestParseCron:
    def test_standard_daily(self):
        hour, minute = _parse_cron("0 6 * * *")
        assert hour == 6
        assert minute == 0

    def test_custom_time(self):
        hour, minute = _parse_cron("30 8 * * *")
        assert hour == 8
        assert minute == 30

    def test_midnight(self):
        hour, minute = _parse_cron("0 0 * * *")
        assert hour == 0
        assert minute == 0

    def test_invalid_too_few_fields(self):
        # Only 1 field - should trigger length check, not int conversion error
        with pytest.raises(ValueError):
            _parse_cron("0")

    def test_invalid_hour(self):
        with pytest.raises(ValueError):
            _parse_cron("0 25 * * *")

    def test_invalid_minute(self):
        with pytest.raises(ValueError):
            _parse_cron("60 6 * * *")


class TestNextRunTime:
    def test_future_time_today(self):
        tz = ZoneInfo("America/Denver")
        hour, minute = 23, 59
        mock_now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=tz)

        with patch("entrypoint.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = _next_run_time(hour, minute, tz)
            assert result.date() == mock_now.date()
            assert result.hour == hour
            assert result.minute == minute

    def test_past_time_tomorrow(self):
        tz = ZoneInfo("America/Denver")
        hour, minute = 1, 0
        mock_now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=tz)

        with patch("entrypoint.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = _next_run_time(hour, minute, tz)
            expected_date = mock_now.date() + timedelta(days=1)
            assert result.date() == expected_date
            assert result.hour == hour
            assert result.minute == minute

    def test_exact_current_time(self):
        tz = ZoneInfo("America/Denver")
        hour, minute = 12, 0
        mock_now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=tz)

        with patch("entrypoint.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = _next_run_time(hour, minute, tz)
            # When now == run_time, should schedule for tomorrow
            expected_date = mock_now.date() + timedelta(days=1)
            assert result.date() == expected_date

    def test_spring_forward_transition(self):
        tz = ZoneInfo("America/Denver")
        hour, minute = 3, 0
        mock_now = datetime(2026, 3, 8, 1, 30, 0, tzinfo=tz)

        with patch("entrypoint.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = _next_run_time(hour, minute, tz)
            assert result.date() == mock_now.date()
            assert result.hour == hour
            assert result.minute == minute

    def test_fall_back_transition(self):
        tz = ZoneInfo("America/Denver")
        hour, minute = 1, 30
        mock_now = datetime(2026, 11, 1, 2, 15, 0, tzinfo=tz)

        with patch("entrypoint.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = _next_run_time(hour, minute, tz)
            expected_date = mock_now.date() + timedelta(days=1)
            assert result.date() == expected_date
            assert result.hour == hour
            assert result.minute == minute


class TestEntrypointMain:
    @patch("entrypoint.run")
    @patch("entrypoint.time.sleep")
    def test_now_flag_runs_immediately(self, mock_sleep, mock_run):
        import sys
        from entrypoint import main

        sys.argv = ["entrypoint.py", "--now"]
        main()
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("entrypoint.run")
    @patch("entrypoint.time.sleep")
    @patch("entrypoint.datetime")
    @patch("entrypoint.load_config")
    def test_scheduler_mode_sleeps(
        self, mock_load_config, mock_dt, mock_sleep, mock_run
    ):
        import sys
        from entrypoint import main

        sys.argv = ["entrypoint.py"]
        call_count = 0

        def fake_sleep(n):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                raise KeyboardInterrupt("Test exit")

        mock_sleep.side_effect = fake_sleep
        mock_dt.now.return_value = datetime(2026, 4, 10, 12, 0, 0)
        mock_load_config.return_value = {"schedule": {"cron": "0 6 * * *"}}

        with pytest.raises(KeyboardInterrupt):
            main()

        # Should have slept a few times (scheduler loop)
        assert call_count > 1

    @patch("entrypoint.run")
    @patch("entrypoint.time.sleep")
    @patch("entrypoint.datetime")
    @patch("entrypoint._next_run_time")
    def test_scheduler_handles_pipeline_crash(
        self, mock_next_run, mock_dt, mock_sleep, mock_run
    ):
        import sys
        from entrypoint import main

        sys.argv = ["entrypoint.py"]
        call_count = 0

        def fake_sleep(n):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                raise KeyboardInterrupt("Test exit")

        mock_sleep.side_effect = fake_sleep
        mock_run.side_effect = Exception("Pipeline crashed")

        # Return a past time so `now >= next_run` is True
        tz = ZoneInfo("America/Denver")
        past_time = datetime(2026, 4, 9, 6, 0, 0, tzinfo=tz)
        mock_next_run.return_value = past_time

        # Mock datetime.now to return a time after the past next_run
        mock_dt.now.return_value = datetime(2026, 4, 10, 12, 0, 0, tzinfo=tz)

        # Should not raise — crash is caught and logged
        with pytest.raises(KeyboardInterrupt):
            main()

        # Pipeline should have been called
        mock_run.assert_called()
