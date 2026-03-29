"""
outlook_client.py – Microsoft Graph API client for Outlook Calendar.

Authentication
--------------
Uses MSAL's *device code flow*, which works without a client secret stored in
code.  On the first run the user must visit a URL and enter a short code in a
browser.  The resulting token is cached on disk so subsequent runs are silent.

Usage
-----
    from outlook_client import OutlookCalendarClient
    client = OutlookCalendarClient()
    client.authenticate()
    client.create_event(event_dict)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import msal
import requests
from dateutil import parser as dateutil_parser
import pytz

import config

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Date/time helpers
# ---------------------------------------------------------------------------

def _parse_datetime(
    date_str: Optional[str],
    time_str: Optional[str],
    year: int,
    tz: pytz.BaseTzInfo,
) -> Optional[datetime]:
    """
    Combine a date string like "Monday, March 31" and a time like "6:30 PM"
    into an aware datetime.  Returns ``None`` if parsing fails.
    """
    if not date_str or not time_str:
        return None

    # Normalise the time string (remove extra spaces around AM/PM)
    time_str = time_str.strip()

    try:
        # Inject the year so dateutil can parse correctly.
        combined = f"{date_str} {year} {time_str}"
        dt_naive = dateutil_parser.parse(combined, fuzzy=True)
        return tz.localize(dt_naive)
    except Exception:
        logger.debug("Could not parse datetime: %r + %r", date_str, time_str)
        return None


def _to_graph_datetime(dt: datetime) -> str:
    """Format a datetime for the Microsoft Graph API body (ISO-8601 without Z suffix)."""
    return dt.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OutlookCalendarClient:
    """Thin wrapper around Microsoft Graph calendar endpoints."""

    def __init__(
        self,
        client_id: str = config.CLIENT_ID,
        tenant_id: str = config.TENANT_ID,
        scopes: list[str] = None,
        cache_file: str = config.TOKEN_CACHE_FILE,
    ) -> None:
        self._client_id = client_id
        self._tenant_id = tenant_id
        self._scopes = scopes or config.GRAPH_SCOPES
        self._cache_file = cache_file
        self._token: Optional[str] = None
        self._cache = msal.SerializableTokenCache()
        self._app: Optional[msal.PublicClientApplication] = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        if os.path.exists(self._cache_file):
            with open(self._cache_file, "r", encoding="utf-8") as fh:
                self._cache.deserialize(fh.read())

    def _save_cache(self) -> None:
        if self._cache.has_state_changed:
            with open(self._cache_file, "w", encoding="utf-8") as fh:
                fh.write(self._cache.serialize())
            logger.debug("Token cache saved to %s", self._cache_file)

    def _build_app(self) -> msal.PublicClientApplication:
        authority = f"https://login.microsoftonline.com/{self._tenant_id}"
        return msal.PublicClientApplication(
            self._client_id,
            authority=authority,
            token_cache=self._cache,
        )

    def authenticate(self) -> None:
        """
        Acquire an access token using the OAuth2 device code flow.

        If a valid cached token exists it is reused silently; otherwise the
        user is prompted to authenticate in a browser.
        """
        self._load_cache()
        self._app = self._build_app()

        # Try silent authentication first (uses cached refresh token).
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(self._scopes, account=accounts[0])
            if result and "access_token" in result:
                self._token = result["access_token"]
                logger.info("Authenticated silently from token cache.")
                self._save_cache()
                return

        # Fall back to interactive device code flow.
        flow = self._app.initiate_device_flow(scopes=self._scopes)
        if "user_code" not in flow:
            raise RuntimeError(
                f"Failed to initiate device flow: {json.dumps(flow, indent=2)}"
            )

        print("\n" + "=" * 60)
        print("ACTION REQUIRED – Microsoft Authentication")
        print("=" * 60)
        print(flow["message"])
        print("=" * 60 + "\n")

        result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(
                f"Authentication failed: {result.get('error_description', result)}"
            )

        self._token = result["access_token"]
        logger.info("Authenticated successfully via device code flow.")
        self._save_cache()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("Not authenticated – call authenticate() first.")
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _post(self, url: str, payload: dict) -> dict:
        response = requests.post(url, headers=self._headers(), json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Calendar operations
    # ------------------------------------------------------------------

    def create_event(self, event: dict, year: int = None) -> Optional[dict]:
        """
        Create a single calendar event on the configured Outlook account.

        Parameters
        ----------
        event:
            A dict as returned by ``scraper.fetch_schedule``.
        year:
            The calendar year of the event.  Defaults to the current year.

        Returns
        -------
        dict | None
            The Graph API response for the created event, or ``None`` if the
            event could not be mapped to valid datetimes.
        """
        if year is None:
            year = datetime.now().year

        tz = pytz.timezone(config.DEFAULT_TIMEZONE)

        date_str = event.get("date")
        start_str = event.get("start_time")
        end_str = event.get("end_time")

        start_dt = _parse_datetime(date_str, start_str, year, tz)

        if start_dt is None:
            # No valid start time – create an all-day or best-effort event.
            if date_str:
                try:
                    # Treat as an all-day event.
                    day_dt = dateutil_parser.parse(f"{date_str} {year}", fuzzy=True)
                    start_dt = tz.localize(day_dt.replace(hour=0, minute=0, second=0))
                    end_dt = start_dt + timedelta(hours=1)
                except Exception:
                    logger.warning(
                        "Skipping event %r – cannot determine start time.",
                        event.get("title"),
                    )
                    return None
            else:
                logger.warning(
                    "Skipping event %r – no date or time information.", event.get("title")
                )
                return None
        else:
            if end_str:
                end_dt = _parse_datetime(date_str, end_str, year, tz)
            else:
                end_dt = None

            if end_dt is None:
                end_dt = start_dt + timedelta(hours=1)

        body_content = event.get("description") or ""
        if event.get("location"):
            body_content = f"Location: {event['location']}\n\n{body_content}".strip()

        payload: dict = {
            "subject": event.get("title", "CinemaCon Event"),
            "body": {
                "contentType": "text",
                "content": body_content,
            },
            "start": {
                "dateTime": _to_graph_datetime(start_dt),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": _to_graph_datetime(end_dt),
                "timeZone": "UTC",
            },
        }

        if event.get("location"):
            payload["location"] = {"displayName": event["location"]}

        url = f"{GRAPH_BASE}/users/{config.CALENDAR_USER}/calendar/events"
        created = self._post(url, payload)
        logger.info("Created event: %s", created.get("id"))
        return created
