"""
agent.py – CinemaCon Schedule → Outlook Calendar Agent

This is the main entry point.  Running this script will:

1. Fetch the schedule from https://www.cinemacon.com/en/schedule-of-events
2. Parse all events from the page.
3. Add each event to the Outlook calendar for harshit.thakkar@qubecinema.com
   using the Microsoft Graph API (authenticated via the OAuth2 device code flow).

Usage
-----
    python agent.py [--year YEAR] [--dry-run] [--url URL]

Options
-------
--year      Calendar year to assign to events (default: current year).
--dry-run   Parse and display events without writing to Outlook.
--url       Override the schedule URL (default from config.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

import config
from scraper import fetch_schedule
from outlook_client import OutlookCalendarClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy the CinemaCon schedule to an Outlook calendar.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Calendar year for events (default: current year).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and display events without writing to Outlook.",
    )
    parser.add_argument(
        "--url",
        default=config.CINEMACON_SCHEDULE_URL,
        help="Override the schedule URL.",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(url: str, year: int, dry_run: bool = False) -> None:
    """
    Fetch the CinemaCon schedule and add all events to Outlook.

    Parameters
    ----------
    url:
        Schedule page URL.
    year:
        Year to use when constructing event datetimes.
    dry_run:
        If ``True``, print events to stdout instead of writing to Outlook.
    """
    logger.info("Starting CinemaCon → Outlook agent (year=%d, dry_run=%s)", year, dry_run)

    # ── Step 1: Scrape schedule ──────────────────────────────────────────────
    events = fetch_schedule(url)

    if not events:
        logger.warning(
            "No events were found on the schedule page.  "
            "The page structure may have changed – please inspect %s manually "
            "and update scraper.py if needed.",
            url,
        )
        sys.exit(1)

    logger.info("Found %d event(s) on the schedule page.", len(events))

    # ── Step 2: Dry run – just print ─────────────────────────────────────────
    if dry_run:
        print(f"\n{'=' * 60}")
        print(f"DRY RUN – {len(events)} event(s) found (not written to Outlook)")
        print("=" * 60)
        for i, ev in enumerate(events, 1):
            print(f"\n[{i}] {ev.get('title', '(no title)')}")
            print(f"     Date : {ev.get('date', 'N/A')}")
            print(f"     Start: {ev.get('start_time', 'N/A')}")
            print(f"     End  : {ev.get('end_time', 'N/A')}")
            print(f"     Loc  : {ev.get('location', 'N/A')}")
            if ev.get("description"):
                print(f"     Desc : {ev['description'][:80]}...")
        print()
        return

    # ── Step 3: Authenticate ─────────────────────────────────────────────────
    client = OutlookCalendarClient()
    logger.info(
        "Authenticating as %s (tenant: %s) …",
        config.CALENDAR_USER,
        config.TENANT_ID,
    )
    client.authenticate()

    # ── Step 4: Create events ─────────────────────────────────────────────────
    created = 0
    skipped = 0
    errors = 0

    for event in events:
        title = event.get("title", "(no title)")
        try:
            result = client.create_event(event, year=year)
            if result:
                created += 1
                logger.info("  ✓ Created: %s", title)
            else:
                skipped += 1
                logger.warning("  – Skipped (no valid datetime): %s", title)
        except Exception as exc:
            errors += 1
            logger.error("  ✗ Error creating %r: %s", title, exc)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("Summary")
    print("=" * 60)
    print(f"  Events found  : {len(events)}")
    print(f"  Created       : {created}")
    print(f"  Skipped       : {skipped}")
    print(f"  Errors        : {errors}")
    print(f"  Calendar      : {config.CALENDAR_USER}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    run(url=args.url, year=args.year, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
