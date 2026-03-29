"""
Main entry point for the CinemaCon Calendar Management tool.

Usage:
    python main.py [--output OUTPUT] [--url URL] [--verbose]

This script:
1. Scrapes the CinemaCon schedule from https://www.cinemacon.com/en/schedule-of-events
2. Parses all events from the page
3. Generates a .ics calendar file that can be imported into Outlook
   (or any iCalendar-compatible application)
"""

import argparse
import logging
import sys
from pathlib import Path

from calendar_integration import create_calendar_file
from scraper import CINEMACON_SCHEDULE_URL, scrape_events


def configure_logging(verbose: bool = False) -> None:
    """Set up console logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Scrape CinemaCon schedule and create an Outlook-compatible calendar file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py\n"
            "  python main.py --output my_calendar.ics\n"
            "  python main.py --url https://www.cinemacon.com/en/schedule-of-events --verbose\n"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        default="cinemacon_events.ics",
        metavar="FILE",
        help="Output .ics file path (default: cinemacon_events.ics)",
    )
    parser.add_argument(
        "--url",
        "-u",
        default=CINEMACON_SCHEDULE_URL,
        metavar="URL",
        help=f"CinemaCon schedule URL (default: {CINEMACON_SCHEDULE_URL})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run the CinemaCon scraper and generate a calendar file.

    Returns:
        0 on success, non-zero on failure.
    """
    args = parse_args(argv)
    configure_logging(args.verbose)
    logger = logging.getLogger(__name__)

    logger.info("=== CinemaCon Calendar Manager ===")
    logger.info("Source URL : %s", args.url)
    logger.info("Output file: %s", args.output)

    try:
        logger.info("Step 1/2  Scraping schedule …")
        events = scrape_events(args.url)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to scrape schedule: %s", exc)
        return 1

    if not events:
        logger.warning(
            "No events were found on the schedule page.  "
            "The page layout may have changed.  "
            "Please check %s manually.",
            args.url,
        )
        return 1

    logger.info("Found %d event(s).", len(events))
    for i, evt in enumerate(events, 1):
        start = evt.start_time.strftime("%a %b %d  %H:%M") if evt.start_time else "TBD"
        end = evt.end_time.strftime("%H:%M") if evt.end_time else "TBD"
        logger.info("  %2d. [%s – %s]  %s", i, start, end, evt.title)

    try:
        logger.info("Step 2/2  Writing calendar file …")
        output_path = create_calendar_file(events, output_path=Path(args.output))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to write calendar file: %s", exc)
        return 1

    logger.info("Done!  Import '%s' into Outlook (or any iCalendar app) to add", output_path)
    logger.info("       these events to your calendar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
