"""
Tests for the CinemaCon calendar management scripts.
"""

import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scraper import (
    CinemaConEvent,
    _build_date,
    _parse_time_range,
    parse_schedule,
)
from calendar_integration import (
    build_calendar,
    create_calendar_file,
    event_to_vevent,
    save_calendar,
)
from main import main


# ───────────────────────────── fixtures ──────────────────────────────────────


@pytest.fixture()
def sample_events():
    return [
        CinemaConEvent(
            title="Sony Pictures Presentation",
            start_time=datetime(2025, 3, 31, 18, 30),
            end_time=datetime(2025, 3, 31, 20, 45),
            location="The Colosseum, Caesars Palace, Las Vegas, NV",
            description="Source: https://www.cinemacon.com/en/schedule-of-events",
        ),
        CinemaConEvent(
            title="Lionsgate Presentation",
            start_time=datetime(2025, 4, 1, 9, 0),
            end_time=datetime(2025, 4, 1, 11, 30),
            location="The Colosseum, Caesars Palace, Las Vegas, NV",
            description="Source: https://www.cinemacon.com/en/schedule-of-events",
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# scraper tests
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildDate:
    def test_standard_format(self):
        dt = _build_date("Monday, March 31", 2025)
        assert dt is not None
        assert dt.month == 3
        assert dt.day == 31
        assert dt.year == 2025

    def test_without_weekday(self):
        dt = _build_date("April 1", 2025)
        assert dt is not None
        assert dt.month == 4
        assert dt.day == 1

    def test_invalid_returns_none(self):
        dt = _build_date("not a date", 2025)
        assert dt is None


class TestParseTimeRange:
    """Tests for the _parse_time_range helper."""

    base = datetime(2025, 3, 31)

    def test_simple_range_am_pm(self):
        start, end = _parse_time_range("9:00 a.m. – 11:30 a.m.", self.base)
        assert start is not None and start.hour == 9 and start.minute == 0
        assert end is not None and end.hour == 11 and end.minute == 30

    def test_pm_only_end(self):
        start, end = _parse_time_range("6:30–8:45 p.m.", self.base)
        assert start is not None and start.hour == 18 and start.minute == 30
        assert end is not None and end.hour == 20 and end.minute == 45

    def test_single_time(self):
        start, end = _parse_time_range("10:00 a.m.", self.base)
        assert start is not None and start.hour == 10
        assert end is None

    def test_24h_range(self):
        start, end = _parse_time_range("14:00 - 15:30", self.base)
        assert start is not None and start.hour == 14
        assert end is not None and end.hour == 15 and end.minute == 30

    def test_malformed_returns_none_pair(self):
        start, end = _parse_time_range("no time here", self.base)
        assert start is None


class TestParseSchedule:
    """Tests for parse_schedule with various HTML structures."""

    def _html_table(self) -> str:
        return textwrap.dedent("""
            <html><body>
            <table>
              <tr><td colspan="3"><strong>Monday, March 31, 2025</strong></td></tr>
              <tr>
                <td>6:30–8:45 p.m.</td>
                <td>Sony Pictures Presentation</td>
                <td>The Colosseum</td>
              </tr>
              <tr>
                <td colspan="3"><strong>Tuesday, April 1, 2025</strong></td>
              </tr>
              <tr>
                <td>9:00 a.m. - 11:30 a.m.</td>
                <td>Lionsgate Presentation</td>
                <td>The Colosseum</td>
              </tr>
            </table>
            </body></html>
        """)

    def _html_heuristic(self) -> str:
        return textwrap.dedent("""
            <html><body>
            <h2>Monday, March 31, 2025</h2>
            <p>6:30 p.m. - 8:45 p.m. Sony Pictures</p>
            <h2>Tuesday, April 1, 2025</h2>
            <p>9:00 a.m. - 11:30 a.m. Lionsgate</p>
            </body></html>
        """)

    def test_table_schedule_parsed(self):
        events = parse_schedule(self._html_table())
        assert len(events) >= 2
        titles = [e.title for e in events]
        assert any("Sony" in t for t in titles)
        assert any("Lionsgate" in t for t in titles)

    def test_events_have_start_times(self):
        events = parse_schedule(self._html_table())
        for evt in events:
            assert evt.start_time is not None, f"Event {evt.title!r} has no start time"

    def test_heuristic_fallback(self):
        events = parse_schedule(self._html_heuristic())
        assert len(events) >= 2

    def test_empty_page_returns_empty_list(self):
        events = parse_schedule("<html><body><p>Nothing here.</p></body></html>")
        assert events == []

    def test_year_detected_from_page(self):
        events = parse_schedule(self._html_table())
        for evt in events:
            if evt.start_time:
                assert evt.start_time.year == 2025


# ──────────────────────────────────────────────────────────────────────────────
# calendar_integration tests
# ──────────────────────────────────────────────────────────────────────────────


class TestEventToVevent:
    def test_basic_fields(self, sample_events):
        evt = sample_events[0]
        vevent = event_to_vevent(evt)
        assert str(vevent.get("summary")) == "Sony Pictures Presentation"
        assert vevent.get("dtstart") is not None
        assert vevent.get("dtend") is not None
        assert vevent.get("location") is not None
        assert vevent.get("uid") is not None

    def test_no_end_time_adds_default_duration(self):
        evt = CinemaConEvent(
            title="Mystery Panel",
            start_time=datetime(2025, 4, 2, 14, 0),
            end_time=None,
        )
        vevent = event_to_vevent(evt)
        start = vevent.decoded("dtstart")
        end = vevent.decoded("dtend")
        diff = end - start
        assert diff == timedelta(hours=1)

    def test_no_start_time_creates_allday_event(self):
        evt = CinemaConEvent(title="TBD Event")
        vevent = event_to_vevent(evt)
        # All-day events use date (not datetime) objects
        from datetime import date
        assert isinstance(vevent.decoded("dtstart"), date)

    def test_utc_conversion(self):
        evt = CinemaConEvent(
            title="Evening Show",
            start_time=datetime(2025, 3, 31, 18, 30),  # naive → treated as PDT
        )
        vevent = event_to_vevent(evt)
        start = vevent.decoded("dtstart")
        # PDT = UTC-7, so 18:30 PDT → 01:30 UTC next day
        assert start.tzinfo == timezone.utc
        assert start.hour == 1
        assert start.minute == 30


class TestBuildCalendar:
    def test_event_count(self, sample_events):
        cal = build_calendar(sample_events)
        vevents = list(cal.walk("VEVENT"))
        assert len(vevents) == len(sample_events)

    def test_calendar_metadata(self, sample_events):
        cal = build_calendar(sample_events, calendar_name="Test Cal")
        assert cal.get("version") is not None
        assert cal.get("prodid") is not None

    def test_empty_events_list(self):
        cal = build_calendar([])
        vevents = list(cal.walk("VEVENT"))
        assert len(vevents) == 0


class TestSaveCalendar:
    def test_file_created(self, tmp_path, sample_events):
        cal = build_calendar(sample_events)
        output = tmp_path / "test_events.ics"
        result = save_calendar(cal, output)
        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

    def test_valid_ics_content(self, tmp_path, sample_events):
        cal = build_calendar(sample_events)
        output = tmp_path / "test_events.ics"
        save_calendar(cal, output)
        content = output.read_text()
        assert "BEGIN:VCALENDAR" in content
        assert "BEGIN:VEVENT" in content
        assert "END:VEVENT" in content
        assert "END:VCALENDAR" in content

    def test_default_path(self, tmp_path, sample_events, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cal = build_calendar(sample_events)
        result = save_calendar(cal)
        assert result.name == "cinemacon_events.ics"
        assert result.exists()


class TestCreateCalendarFile:
    def test_creates_ics_file(self, tmp_path, sample_events):
        output = tmp_path / "events.ics"
        result = create_calendar_file(sample_events, output_path=output)
        assert result == output
        assert output.exists()

    def test_creates_parent_dirs(self, tmp_path, sample_events):
        output = tmp_path / "nested" / "dir" / "events.ics"
        result = create_calendar_file(sample_events, output_path=output)
        assert result.exists()


# ──────────────────────────────────────────────────────────────────────────────
# main() integration tests
# ──────────────────────────────────────────────────────────────────────────────


class TestMain:
    """Integration tests for the main() entry point (network calls are mocked)."""

    def _make_events(self):
        return [
            CinemaConEvent(
                title="Sony Presentation",
                start_time=datetime(2025, 3, 31, 18, 30),
                end_time=datetime(2025, 3, 31, 20, 45),
            )
        ]

    def test_success_exit_code(self, tmp_path):
        output = str(tmp_path / "out.ics")
        with patch("main.scrape_events", return_value=self._make_events()):
            code = main(["--output", output])
        assert code == 0
        assert Path(output).exists()

    def test_no_events_returns_nonzero(self, tmp_path):
        output = str(tmp_path / "out.ics")
        with patch("main.scrape_events", return_value=[]):
            code = main(["--output", output])
        assert code != 0

    def test_scrape_error_returns_nonzero(self, tmp_path):
        output = str(tmp_path / "out.ics")
        with patch("main.scrape_events", side_effect=ConnectionError("network down")):
            code = main(["--output", output])
        assert code != 0

    def test_custom_url_forwarded(self, tmp_path):
        output = str(tmp_path / "out.ics")
        custom_url = "https://example.com/schedule"
        with patch("main.scrape_events", return_value=self._make_events()) as mock_scrape:
            main(["--output", output, "--url", custom_url])
        mock_scrape.assert_called_once_with(custom_url)

    def test_verbose_flag_accepted(self, tmp_path):
        output = str(tmp_path / "out.ics")
        with patch("main.scrape_events", return_value=self._make_events()):
            code = main(["--output", output, "--verbose"])
        assert code == 0
