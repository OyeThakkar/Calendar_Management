"""
tests/test_scraper.py – Unit tests for the scraper module.
"""

from __future__ import annotations

import textwrap
import unittest
from unittest.mock import MagicMock, patch

import requests as req

from scraper import (
    _clean,
    _parse_time_range,
    _parse_structured,
    _parse_day_sections,
    _fallback_parse,
    fetch_schedule,
)
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------

class TestClean(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(_clean("  foo   bar  "), "foo bar")

    def test_none_input(self):
        self.assertIsNone(_clean(None))

    def test_empty_string(self):
        self.assertIsNone(_clean(""))

    def test_only_whitespace(self):
        self.assertIsNone(_clean("   "))

    def test_normal_string(self):
        self.assertEqual(_clean("hello"), "hello")


# ---------------------------------------------------------------------------
# _parse_time_range
# ---------------------------------------------------------------------------

class TestParseTimeRange(unittest.TestCase):
    def test_full_range_dash(self):
        start, end = _parse_time_range("6:30 PM \u2013 8:45 PM")
        self.assertEqual(start, "6:30 PM")
        self.assertEqual(end, "8:45 PM")

    def test_full_range_hyphen(self):
        start, end = _parse_time_range("9:00 AM - 11:30 AM")
        self.assertEqual(start, "9:00 AM")
        self.assertEqual(end, "11:30 AM")

    def test_start_only(self):
        start, end = _parse_time_range("10:00 AM")
        self.assertEqual(start, "10:00 AM")
        self.assertIsNone(end)

    def test_no_time(self):
        start, end = _parse_time_range("TBD")
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_empty_string(self):
        start, end = _parse_time_range("")
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_time_in_sentence(self):
        start, end = _parse_time_range("Doors open at 9:00 AM for the keynote.")
        self.assertEqual(start, "9:00 AM")
        self.assertIsNone(end)


# ---------------------------------------------------------------------------
# _parse_structured – table layout
# ---------------------------------------------------------------------------

class TestParseStructuredTable(unittest.TestCase):
    def _make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def test_simple_table(self):
        html = textwrap.dedent("""\
            <table>
              <tr><td>6:30 PM \u2013 8:45 PM</td><td>Sony Pictures Presentation</td><td>The Colosseum</td></tr>
              <tr><td>9:00 AM \u2013 11:30 AM</td><td>Lionsgate Presentation</td></tr>
            </table>
        """)
        soup = self._make_soup(html)
        events = _parse_structured(soup)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Sony Pictures Presentation")
        self.assertEqual(events[0]["start_time"], "6:30 PM")
        self.assertEqual(events[0]["end_time"], "8:45 PM")
        self.assertEqual(events[0]["location"], "The Colosseum")
        self.assertEqual(events[1]["title"], "Lionsgate Presentation")

    def test_table_header_row_included(self):
        html = textwrap.dedent("""\
            <table>
              <tr><th>Time</th><th>Event</th></tr>
              <tr><td>10:00 AM</td><td>Keynote</td></tr>
            </table>
        """)
        soup = self._make_soup(html)
        events = _parse_structured(soup)
        titles = [e["title"] for e in events]
        self.assertIn("Keynote", titles)

    def test_empty_page(self):
        soup = self._make_soup("<html><body></body></html>")
        events = _parse_structured(soup)
        self.assertEqual(events, [])


# ---------------------------------------------------------------------------
# _parse_day_sections
# ---------------------------------------------------------------------------

class TestParseDaySections(unittest.TestCase):
    def _make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def test_day_heading_with_sessions(self):
        html = textwrap.dedent("""\
            <div>
              <h2>Monday, March 31</h2>
              <div>
                <p>Sony Pictures Presentation 6:30 PM \u2013 8:45 PM</p>
              </div>
            </div>
        """)
        soup = self._make_soup(html)
        events = _parse_day_sections(soup)
        self.assertTrue(len(events) >= 1)
        ev = events[0]
        self.assertIn("Sony Pictures", ev["title"])
        self.assertEqual(ev["start_time"], "6:30 PM")

    def test_multiple_days(self):
        html = textwrap.dedent("""\
            <div>
              <h2>Monday, March 31</h2>
              <div><p>Session A 9:00 AM \u2013 10:00 AM</p></div>
              <h2>Tuesday, April 1</h2>
              <div><p>Session B 2:00 PM \u2013 3:00 PM</p></div>
            </div>
        """)
        soup = self._make_soup(html)
        events = _parse_day_sections(soup)
        self.assertTrue(len(events) >= 2)
        dates = {e["date"] for e in events if e["date"]}
        self.assertTrue(any("Monday" in d for d in dates))
        self.assertTrue(any("Tuesday" in d for d in dates))


# ---------------------------------------------------------------------------
# _fallback_parse
# ---------------------------------------------------------------------------

class TestFallbackParse(unittest.TestCase):
    def _make_soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def test_finds_time_bearing_elements(self):
        html = textwrap.dedent("""\
            <div>
              <p>Opening Ceremony 10:00 AM</p>
              <p>Awards Luncheon 12:30 PM \u2013 2:00 PM</p>
              <p>No time here</p>
            </div>
        """)
        soup = self._make_soup(html)
        events = _fallback_parse(soup, "https://example.com")
        titles = [e["title"] for e in events]
        self.assertTrue(any("Opening Ceremony" in t for t in titles))
        self.assertTrue(any("Awards Luncheon" in t for t in titles))

    def test_deduplicates(self):
        html = textwrap.dedent("""\
            <div>
              <span>Session X 9:00 AM</span>
              <span>Session X 9:00 AM</span>
            </div>
        """)
        soup = self._make_soup(html)
        events = _fallback_parse(soup, "https://example.com")
        self.assertEqual(len(events), 1)


# ---------------------------------------------------------------------------
# fetch_schedule (integration-style with mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetchSchedule(unittest.TestCase):
    def _html_with_table(self) -> str:
        return textwrap.dedent("""\
            <html><body>
              <h1>Schedule of Events</h1>
              <table>
                <tr><td>6:30 PM \u2013 8:45 PM</td><td>Sony Presentation</td><td>The Colosseum</td></tr>
                <tr><td>9:00 AM \u2013 11:30 AM</td><td>Lionsgate Presentation</td></tr>
              </table>
            </body></html>
        """)

    def _html_with_days(self) -> str:
        return textwrap.dedent("""\
            <html><body>
              <h2>Monday, March 31</h2>
              <p>Opening Keynote 9:00 AM \u2013 10:30 AM</p>
              <h2>Tuesday, April 1</h2>
              <p>Studio Showcase 2:00 PM \u2013 4:00 PM</p>
            </body></html>
        """)

    @patch("scraper._fetch_html")
    def test_structured_table_path(self, mock_fetch: MagicMock):
        mock_fetch.return_value = self._html_with_table()
        events = fetch_schedule("https://fake.url/schedule")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Sony Presentation")

    @patch("scraper._fetch_html")
    def test_day_section_path(self, mock_fetch: MagicMock):
        mock_fetch.return_value = self._html_with_days()
        events = fetch_schedule("https://fake.url/schedule")
        self.assertGreaterEqual(len(events), 2)

    @patch("scraper._fetch_html")
    def test_empty_page_returns_empty_list(self, mock_fetch: MagicMock):
        mock_fetch.return_value = "<html><body><p>No schedule yet.</p></body></html>"
        events = fetch_schedule("https://fake.url/schedule")
        self.assertEqual(events, [])

    @patch("scraper._fetch_html")
    def test_http_error_propagates(self, mock_fetch: MagicMock):
        mock_fetch.side_effect = req.HTTPError("404 Not Found")
        with self.assertRaises(req.HTTPError):
            fetch_schedule("https://fake.url/schedule")


if __name__ == "__main__":
    unittest.main()
