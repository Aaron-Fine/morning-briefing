"""Tests for sources/launches.py — space launch data fetching."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sources.launches import (
    fetch_upcoming_launches,
    _get_launch_site,
    HIGH_PRIORITY_TYPES,
    LAUNCH_LIBRARY_URL,  # noqa: F401  (public constant re-exported for callers)
)


def _make_launch_response(launches):
    """Helper to build a mock Launch Library 2 API response."""
    return {"count": len(launches), "results": launches}


def _make_mock_launch(name="Test Launch", days_from_now=3, mission_type="government"):
    future_date = (
        datetime.now(timezone.utc) + timedelta(days=days_from_now)
    ).isoformat()
    return {
        "name": name,
        "net": future_date,
        "rocket": {"configuration": {"full_name": "Falcon 9"}},
        "launch_service_provider": {"name": "SpaceX"},
        "pad": {
            "name": "SLC-40",
            "location": {"name": "Cape Canaveral, FL"},
        },
        "mission": {
            "type": mission_type,
            "description": "Test mission description",
        },
        "status": {"name": "Go"},
    }


class TestFetchUpcomingLaunches:
    @patch("sources.launches.http_get_json")
    def test_returns_launches_within_lookahead(self, mock_get):
        mock_get.return_value = _make_launch_response(
            [
                _make_mock_launch("Launch 1", days_from_now=2),
                _make_mock_launch("Launch 2", days_from_now=5),
            ]
        )

        result = fetch_upcoming_launches(lookahead_days=10)
        assert len(result) == 2
        assert result[0]["name"] == "Launch 1"
        assert result[1]["name"] == "Launch 2"

    @patch("sources.launches.http_get_json")
    def test_filters_launch_beyond_cutoff(self, mock_get):
        mock_get.return_value = _make_launch_response(
            [
                _make_mock_launch("Soon", days_from_now=2),
                _make_mock_launch("Later", days_from_now=15),
            ]
        )

        result = fetch_upcoming_launches(lookahead_days=10)
        assert len(result) == 1
        assert result[0]["name"] == "Soon"

    @patch("sources.launches.http_get_json")
    def test_sorts_government_first(self, mock_get):
        mock_get.return_value = _make_launch_response(
            [
                _make_mock_launch("Commercial", days_from_now=2, mission_type="commercial"),
                _make_mock_launch("Military", days_from_now=3, mission_type="military"),
                _make_mock_launch("Civil", days_from_now=1, mission_type="civil"),
            ]
        )

        result = fetch_upcoming_launches(lookahead_days=10)
        assert result[0]["name"] == "Military"
        assert result[1]["name"] == "Civil"
        assert result[2]["name"] == "Commercial"

    @patch("sources.launches.http_get_json")
    def test_returns_empty_on_fetch_failure(self, mock_get):
        # http_get_json returns None on any error.
        mock_get.return_value = None

        result = fetch_upcoming_launches(lookahead_days=10)
        assert result == []

    @patch("sources.launches.http_get_json")
    def test_returns_empty_on_no_results(self, mock_get):
        mock_get.return_value = _make_launch_response([])

        result = fetch_upcoming_launches(lookahead_days=10)
        assert result == []

    @patch("sources.launches.http_get_json")
    def test_launch_date_format(self, mock_get):
        mock_get.return_value = _make_launch_response(
            [_make_mock_launch("Test", days_from_now=3)]
        )

        result = fetch_upcoming_launches(lookahead_days=10)
        assert result[0]["date"].endswith("Z")
        datetime.strptime(result[0]["date"], "%Y-%m-%d %H:%MZ")

    @patch("sources.launches.http_get_json")
    def test_launch_fields_populated(self, mock_get):
        mock_get.return_value = _make_launch_response(
            [_make_mock_launch("Test", days_from_now=3, mission_type="government")]
        )

        result = fetch_upcoming_launches(lookahead_days=10)
        launch = result[0]
        assert launch["name"] == "Test"
        assert launch["vehicle"] == "Falcon 9"
        assert launch["provider"] == "SpaceX"
        assert launch["mission_type"] == "government"
        assert launch["mission_description"] == "Test mission description"
        assert launch["status"] == "Go"
        assert "SLC-40" in launch["launch_site"]
        assert "Cape Canaveral" in launch["launch_site"]

    @patch("sources.launches.http_get_json")
    def test_skips_launches_without_net(self, mock_get):
        mock_get.return_value = _make_launch_response(
            [
                {"name": "No Date", "rocket": {}},
                _make_mock_launch("Valid", days_from_now=3),
            ]
        )

        result = fetch_upcoming_launches(lookahead_days=10)
        assert len(result) == 1
        assert result[0]["name"] == "Valid"

    @patch("sources.launches.http_get_json")
    def test_handles_missing_mission(self, mock_get):
        mock_get.return_value = _make_launch_response(
            [
                {
                    "name": "No Mission",
                    "net": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                    "rocket": {"configuration": {"full_name": "Rocket"}},
                    "launch_service_provider": {"name": "Provider"},
                    "pad": {"name": "Pad", "location": {"name": "Location"}},
                    "mission": None,
                    "status": {"name": "Go"},
                }
            ]
        )

        result = fetch_upcoming_launches(lookahead_days=10)
        assert len(result) == 1
        assert result[0]["mission_type"] == "unknown"
        assert result[0]["mission_description"] == ""


class TestGetLaunchSite:
    def test_full_site_info(self):
        result = _get_launch_site(
            {"pad": {"name": "SLC-40", "location": {"name": "Cape Canaveral, FL"}}}
        )
        assert result == "SLC-40, Cape Canaveral, FL"

    def test_pad_only(self):
        result = _get_launch_site({"pad": {"name": "SLC-40", "location": None}})
        assert result == "SLC-40"

    def test_location_only(self):
        result = _get_launch_site({"pad": {"name": "", "location": {"name": "Baikonur"}}})
        assert result == "Baikonur"

    def test_empty(self):
        result = _get_launch_site({})
        assert result == ""

    def test_no_pad_key(self):
        result = _get_launch_site({"rocket": {}})
        assert result == ""


class TestHighPriorityTypes:
    def test_government_is_high_priority(self):
        assert "government" in HIGH_PRIORITY_TYPES

    def test_military_is_high_priority(self):
        assert "military" in HIGH_PRIORITY_TYPES

    def test_classified_is_high_priority(self):
        assert "classified" in HIGH_PRIORITY_TYPES
