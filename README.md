# Calendar_Management

Scrape the [CinemaCon Schedule of Events](https://www.cinemacon.com/en/schedule-of-events) and generate an `.ics` calendar file that can be imported directly into Microsoft Outlook (or any iCalendar-compatible application such as Google Calendar or Apple Calendar).

---

## How it works

1. **`scraper.py`** – Fetches the CinemaCon schedule page and parses all events (title, date, start/end time, location) using three progressive strategies: table-based, card/heading-based, and a plain-text heuristic fallback.
2. **`calendar_integration.py`** – Converts the parsed events into RFC 5545 iCalendar (`VEVENT`) entries and writes them to an `.ics` file.
3. **`main.py`** – Command-line entry point that ties the two modules together.

---

## Requirements

- Python 3.10+

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

```bash
# Scrape the schedule and write to cinemacon_events.ics (default)
python main.py

# Specify a custom output file
python main.py --output my_calendar.ics

# Enable verbose debug logging
python main.py --verbose

# Use a custom schedule URL
python main.py --url https://www.cinemacon.com/en/schedule-of-events
```

### Importing into Outlook

1. Run `python main.py` to generate `cinemacon_events.ics`.
2. In Outlook, go to **File → Open & Export → Import/Export**.
3. Select **Import an iCalendar (.ics) or vCalendar file (.vcs)** and choose the generated file.
4. The CinemaCon events will be added to your calendar.

---

## Running the tests

```bash
pip install pytest
python -m pytest test_cinemacon.py -v
```
