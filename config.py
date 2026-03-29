"""
Configuration for the CinemaCon Schedule to Outlook Calendar Agent.

Authentication uses the OAuth2 device code flow so no client secret needs to
be stored in code.  Set the three Azure AD values below (or supply them via
environment variables) before running the agent.

Required Azure AD app-registration settings
--------------------------------------------
* API permissions  : Calendars.ReadWrite (delegated)
* Redirect URI     : https://login.microsoftonline.com/common/oauth2/nativeclient
"""

import os

# ---------------------------------------------------------------------------
# Azure AD / Microsoft Identity Platform
# ---------------------------------------------------------------------------

# Tenant ID – use "common" for multi-tenant or paste your specific tenant GUID.
TENANT_ID: str = os.environ.get("AZURE_TENANT_ID", "common")

# Client (Application) ID of your Azure AD app registration.
CLIENT_ID: str = os.environ.get("AZURE_CLIENT_ID", "YOUR_CLIENT_ID_HERE")

# Microsoft Graph scopes required for calendar write access.
GRAPH_SCOPES: list[str] = ["Calendars.ReadWrite"]

# ---------------------------------------------------------------------------
# Target calendar owner
# ---------------------------------------------------------------------------

# The Outlook / Microsoft 365 account that owns the destination calendar.
CALENDAR_USER: str = os.environ.get(
    "CALENDAR_USER", "harshit.thakkar@qubecinema.com"
)

# ---------------------------------------------------------------------------
# Source schedule
# ---------------------------------------------------------------------------

CINEMACON_SCHEDULE_URL: str = (
    "https://www.cinemacon.com/en/schedule-of-events"
)

# Timezone used when the scraped events lack explicit timezone information.
DEFAULT_TIMEZONE: str = "America/Los_Angeles"

# ---------------------------------------------------------------------------
# MSAL token cache path (optional – speeds up repeated runs)
# ---------------------------------------------------------------------------

TOKEN_CACHE_FILE: str = os.environ.get("TOKEN_CACHE_FILE", "token_cache.json")
