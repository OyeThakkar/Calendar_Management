"""
scraper.py – Fetch and parse the CinemaCon schedule-of-events page.

Returns a list of dicts, each representing one session:

    {
        "title":       str,
        "date":        str,          # e.g. "Monday, March 31"
        "start_time":  str | None,   # e.g. "6:30 PM"
        "end_time":    str | None,   # e.g. "8:45 PM"
        "location":    str | None,
        "description": str | None,
    }
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CalendarAgent/1.0; "
        "+https://github.com/OyeThakkar/Calendar_Management)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_TIMEOUT = 30  # seconds


def _fetch_html(url: str) -> str:
    """Download the page and return its HTML text."""
    response = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# Matches patterns like "6:30 PM – 8:45 PM", "9:00 AM - 11:30 AM",
# "10:00 AM", or just "TBD".
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2}\s*[AP]M)"
    r"(?:\s*[–\-]\s*(\d{1,2}:\d{2}\s*[AP]M))?",
    re.IGNORECASE,
)


def _clean(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = " ".join(text.split())
    return cleaned or None


def _parse_time_range(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (start_time, end_time) from a raw time string."""
    match = _TIME_RANGE_RE.search(text)
    if not match:
        return None, None
    start = match.group(1).strip()
    end = match.group(2).strip() if match.group(2) else None
    return start, end


# ---------------------------------------------------------------------------
# Main scraping strategies
# ---------------------------------------------------------------------------

def _parse_structured(soup: BeautifulSoup) -> list[dict]:
    """
    Strategy 1: look for a structured schedule table or repeated event cards.

    CinemaCon typically renders its schedule as a series of styled ``<div>``
    blocks grouped under a day heading, or as an HTML ``<table>``.  This
    strategy tries both layouts.
    """
    events: list[dict] = []

    # ---- try table layout ---------------------------------------------------
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = [_clean(td.get_text()) for td in row.find_all(["td", "th"])]
            if not cells or len(cells) < 2:
                continue
            # Heuristic: first cell is time, second is title
            time_text = cells[0] or ""
            title = cells[1] or ""
            if not title:
                continue
            start, end = _parse_time_range(time_text)
            location = cells[2] if len(cells) > 2 else None
            description = cells[3] if len(cells) > 3 else None
            events.append(
                {
                    "title": title,
                    "date": None,
                    "start_time": start,
                    "end_time": end,
                    "location": location,
                    "description": description,
                }
            )

    if events:
        return events

    # ---- try card / div layout ---------------------------------------------
    # Look for containers that hold both a heading (event name) and a time.
    candidate_selectors = [
        ("div", {"class": re.compile(r"event|schedule|session|program", re.I)}),
        ("article", {}),
        ("li", {"class": re.compile(r"event|session|item", re.I)}),
    ]
    for tag, attrs in candidate_selectors:
        cards: list[Tag] = soup.find_all(tag, attrs)
        if not cards:
            continue
        for card in cards:
            heading = card.find(re.compile(r"h[1-6]"))
            title = _clean(heading.get_text()) if heading else _clean(card.get_text())
            if not title:
                continue
            raw_text = card.get_text(" ", strip=True)
            start, end = _parse_time_range(raw_text)
            # Try to find location clues
            location_el = card.find(
                class_=re.compile(r"location|venue|room|place", re.I)
            )
            location = _clean(location_el.get_text()) if location_el else None
            events.append(
                {
                    "title": title,
                    "date": None,
                    "start_time": start,
                    "end_time": end,
                    "location": location,
                    "description": None,
                }
            )
        if events:
            break

    return events


def _parse_day_sections(soup: BeautifulSoup) -> list[dict]:
    """
    Strategy 2: walk the DOM looking for day-header + sibling event rows.

    Many conference sites group events under a prominent day title like
    "Monday, March 31" followed by a list of sessions.
    """
    events: list[dict] = []

    day_pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
        r"[\s,]+\w+\s+\d{1,2}",
        re.IGNORECASE,
    )

    # Find every element whose text looks like a day heading.
    for el in soup.find_all(string=day_pattern):
        parent = el.parent
        current_date = _clean(str(el))

        # Walk following siblings to collect events until the next day heading.
        sibling = parent.find_next_sibling()
        while sibling:
            sibling_text = sibling.get_text(" ", strip=True)
            if day_pattern.search(sibling_text) and len(sibling_text) < 60:
                break  # reached next day section

            # Extract all time-bearing lines within this sibling block.
            for row in sibling.find_all(
                lambda t: t.name and _TIME_RANGE_RE.search(t.get_text())
            ):
                row_text = row.get_text(" ", strip=True)
                start, end = _parse_time_range(row_text)
                # Remove the time portion to get a cleaner title.
                title = _TIME_RANGE_RE.sub("", row_text).strip(" :-–")
                title = _clean(title)
                if title:
                    events.append(
                        {
                            "title": title,
                            "date": current_date,
                            "start_time": start,
                            "end_time": end,
                            "location": None,
                            "description": None,
                        }
                    )
            sibling = sibling.find_next_sibling()

    return events


def _fallback_parse(soup: BeautifulSoup, url: str) -> list[dict]:
    """
    Strategy 3: generic fallback – extract every visible line that contains
    a time pattern and treat the surrounding text as the event title.
    """
    events: list[dict] = []
    seen: set[str] = set()

    for el in soup.find_all(string=_TIME_RANGE_RE):
        container = el.parent
        text = _clean(container.get_text(" ", strip=True))
        if not text or text in seen:
            continue
        seen.add(text)
        start, end = _parse_time_range(text)
        title = _TIME_RANGE_RE.sub("", text).strip(" :-–")
        title = _clean(title)
        if title:
            events.append(
                {
                    "title": title,
                    "date": None,
                    "start_time": start,
                    "end_time": end,
                    "location": None,
                    "description": None,
                }
            )

    return events


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_schedule(url: str) -> list[dict]:
    """
    Download and parse the CinemaCon schedule page.

    Tries multiple parsing strategies in order of specificity and returns the
    first non-empty result.  Falls back to a generic time-based extraction if
    the structured strategies yield nothing.

    Parameters
    ----------
    url:
        Full URL of the schedule page.

    Returns
    -------
    list[dict]
        Parsed events.  May be empty if the page structure is unrecognised.
    """
    logger.info("Fetching schedule from %s", url)
    html = _fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    # Remove script / style / nav noise.
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()

    events = _parse_structured(soup)
    if events:
        logger.info("Structured parser found %d events", len(events))
        return events

    events = _parse_day_sections(soup)
    if events:
        logger.info("Day-section parser found %d events", len(events))
        return events

    events = _fallback_parse(soup, url)
    logger.info("Fallback parser found %d events", len(events))
    return events
