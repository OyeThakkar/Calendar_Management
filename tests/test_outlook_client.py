"""
tests/test_outlook_client.py – Unit tests for the OutlookCalendarClient.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, mock_open

import pytz
import requests as req

from outlook_client import (
    OutlookCalendarClient,
    _parse_datetime,
    _to_graph_datetime,
)


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------

class TestParseDatetime(unittest.TestCase):
    def setUp(self):
        self.tz = pytz.timezone("America/Los_Angeles")
        self.year = 2025

    def test_valid_date_and_time(self):
        dt = _parse_datetime("Monday, March 31", "6:30 PM", self.year, self.tz)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.hour, 18)
        self.assertEqual(dt.minute, 30)
        self.assertEqual(dt.month, 3)
        self.assertEqual(dt.day, 31)

    def test_none_date(self):
        dt = _parse_datetime(None, "6:30 PM", self.year, self.tz)
        self.assertIsNone(dt)

    def test_none_time(self):
        dt = _parse_datetime("Monday, March 31", None, self.year, self.tz)
        self.assertIsNone(dt)

    def test_invalid_date(self):
        dt = _parse_datetime("Not a date", "6:30 PM", self.year, self.tz)
        # fuzzy=True may still parse partial strings; the important thing is
        # it doesn't raise an exception.
        # Just check it's either None or a datetime.
        self.assertTrue(dt is None or isinstance(dt, datetime))

    def test_timezone_aware(self):
        dt = _parse_datetime("Tuesday, April 1", "9:00 AM", self.year, self.tz)
        self.assertIsNotNone(dt)
        self.assertIsNotNone(dt.tzinfo)


# ---------------------------------------------------------------------------
# _to_graph_datetime
# ---------------------------------------------------------------------------

class TestToGraphDatetime(unittest.TestCase):
    def test_converts_to_utc_iso(self):
        tz = pytz.timezone("America/Los_Angeles")
        dt = tz.localize(datetime(2025, 3, 31, 18, 30, 0))
        result = _to_graph_datetime(dt)
        # LA is UTC-7 during PDT, so 18:30 local → 01:30 UTC next day
        self.assertEqual(result, "2025-04-01T01:30:00")

    def test_format_no_microseconds(self):
        tz = pytz.utc
        dt = datetime(2025, 4, 1, 9, 0, 0, tzinfo=tz)
        result = _to_graph_datetime(dt)
        self.assertEqual(result, "2025-04-01T09:00:00")


# ---------------------------------------------------------------------------
# OutlookCalendarClient.create_event
# ---------------------------------------------------------------------------

class TestCreateEvent(unittest.TestCase):
    def _make_client(self) -> OutlookCalendarClient:
        client = OutlookCalendarClient(
            client_id="fake-client-id",
            tenant_id="common",
        )
        client._token = "fake-token"
        return client

    @patch("outlook_client.requests.post")
    def test_create_event_with_full_info(self, mock_post: MagicMock):
        mock_post.return_value.json.return_value = {"id": "abc123", "subject": "Sony"}
        mock_post.return_value.raise_for_status = MagicMock()

        client = self._make_client()
        event = {
            "title": "Sony Pictures Presentation",
            "date": "Monday, March 31",
            "start_time": "6:30 PM",
            "end_time": "8:45 PM",
            "location": "The Colosseum",
            "description": "Annual studio presentation.",
        }
        result = client.create_event(event, year=2025)

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "abc123")
        mock_post.assert_called_once()
        call_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(call_payload["subject"], "Sony Pictures Presentation")
        self.assertIn("location", call_payload)
        self.assertEqual(call_payload["location"]["displayName"], "The Colosseum")

    @patch("outlook_client.requests.post")
    def test_create_event_without_end_time(self, mock_post: MagicMock):
        mock_post.return_value.json.return_value = {"id": "def456"}
        mock_post.return_value.raise_for_status = MagicMock()

        client = self._make_client()
        event = {
            "title": "Opening Keynote",
            "date": "Tuesday, April 1",
            "start_time": "9:00 AM",
            "end_time": None,
            "location": None,
            "description": None,
        }
        result = client.create_event(event, year=2025)
        self.assertIsNotNone(result)
        call_payload = mock_post.call_args.kwargs["json"]
        # End time should default to start + 1 hour
        self.assertNotEqual(
            call_payload["start"]["dateTime"],
            call_payload["end"]["dateTime"],
        )

    def test_create_event_no_date_returns_none(self):
        client = self._make_client()
        event = {
            "title": "Mystery Event",
            "date": None,
            "start_time": None,
            "end_time": None,
            "location": None,
            "description": None,
        }
        result = client.create_event(event, year=2025)
        self.assertIsNone(result)

    @patch("outlook_client.requests.post")
    def test_create_event_raises_on_http_error(self, mock_post: MagicMock):
        mock_post.return_value.raise_for_status.side_effect = req.HTTPError("403")

        client = self._make_client()
        event = {
            "title": "Some Event",
            "date": "Monday, March 31",
            "start_time": "10:00 AM",
            "end_time": "11:00 AM",
            "location": None,
            "description": None,
        }
        with self.assertRaises(req.HTTPError):
            client.create_event(event, year=2025)

    def test_not_authenticated_raises(self):
        client = OutlookCalendarClient(client_id="x", tenant_id="common")
        # _token is None
        event = {
            "title": "Test",
            "date": "Monday, March 31",
            "start_time": "9:00 AM",
            "end_time": None,
            "location": None,
            "description": None,
        }
        with self.assertRaises(RuntimeError):
            client.create_event(event, year=2025)


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------

class TestTokenCache(unittest.TestCase):
    def test_load_cache_when_file_missing(self):
        client = OutlookCalendarClient(
            client_id="x", tenant_id="common", cache_file="/tmp/nonexistent_abc.json"
        )
        # Should not raise even if file doesn't exist.
        client._load_cache()

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists", return_value=True)
    def test_load_cache_reads_file(self, mock_exists: MagicMock, mock_file: MagicMock):
        mock_file.return_value.read.return_value = "{}"
        client = OutlookCalendarClient(
            client_id="x", tenant_id="common", cache_file="fake_cache.json"
        )
        # We mock the deserialize to avoid real MSAL parsing.
        client._cache.deserialize = MagicMock()
        client._load_cache()
        mock_file.assert_called_once_with("fake_cache.json", "r", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
