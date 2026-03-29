# Calendar_Management

Add Calendar events to Outlook

---

## CinemaCon Schedule → Outlook Calendar Agent

This agent fetches the event schedule from
[cinemacon.com/en/schedule-of-events](https://www.cinemacon.com/en/schedule-of-events)
and adds each session to the Outlook calendar for
**harshit.thakkar@qubecinema.com** using the Microsoft Graph API.

---

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Tested on 3.12 |
| Microsoft 365 account | `harshit.thakkar@qubecinema.com` |
| Azure AD app registration | See setup steps below |

---

### Azure AD App Registration

You need a Microsoft Entra ID (Azure AD) **app registration** before the agent
can write to the calendar:

1. Sign in to [portal.azure.com](https://portal.azure.com) as an admin of the
   `qubecinema.com` tenant.
2. Go to **Azure Active Directory → App registrations → New registration**.
3. Name it (e.g. *CinemaCon Calendar Agent*), select
   **"Accounts in this organisational directory only"**, and click **Register**.
4. Copy the **Application (client) ID** and **Directory (tenant) ID** from the
   overview page.
5. Go to **API permissions → Add a permission → Microsoft Graph →
   Delegated → `Calendars.ReadWrite`**, then click **Grant admin consent**.
6. Go to **Authentication → Add a platform → Mobile and desktop applications**
   and add the redirect URI:
   `https://login.microsoftonline.com/common/oauth2/nativeclient`

---

### Installation

```bash
git clone https://github.com/OyeThakkar/Calendar_Management.git
cd Calendar_Management
pip install -r requirements.txt
```

---

### Configuration

Set the Azure AD values either by editing `config.py` or via environment
variables:

```bash
export AZURE_TENANT_ID="<your-tenant-id>"   # e.g. abc123.onmicrosoft.com or GUID
export AZURE_CLIENT_ID="<your-client-id>"   # Application (client) ID
```

All other settings live in `config.py`:

| Variable | Default | Description |
|---|---|---|
| `CALENDAR_USER` | `harshit.thakkar@qubecinema.com` | Target calendar owner |
| `CINEMACON_SCHEDULE_URL` | `https://www.cinemacon.com/en/schedule-of-events` | Source schedule page |
| `DEFAULT_TIMEZONE` | `America/Los_Angeles` | Timezone for events without explicit TZ |
| `TOKEN_CACHE_FILE` | `token_cache.json` | Local MSAL token cache path |

---

### Usage

#### Dry run (inspect events without writing to Outlook)

```bash
python agent.py --dry-run
```

#### Add events to Outlook

```bash
python agent.py
```

On the first run you will be prompted to open a URL and enter a short code to
authenticate.  The resulting token is cached locally so subsequent runs are
silent.

#### Options

```
--year YEAR   Calendar year for events (default: current year)
--dry-run     Fetch and display events without writing to Outlook
--url URL     Override the schedule URL
```

---

### Project Structure

```
Calendar_Management/
├── agent.py            # Main entry point / orchestration
├── scraper.py          # CinemaCon schedule scraper
├── outlook_client.py   # Microsoft Graph API calendar client
├── config.py           # Configuration constants
├── requirements.txt    # Python dependencies
└── tests/
    ├── test_scraper.py         # Scraper unit tests
    └── test_outlook_client.py  # Outlook client unit tests
```

---

### Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

---

### How It Works

```
agent.py
  │
  ├─ scraper.py ──► GET https://www.cinemacon.com/en/schedule-of-events
  │                    │
  │                    └─ parse HTML (table → day-section → fallback)
  │                         └─ list of event dicts
  │
  └─ outlook_client.py
       │
       ├─ MSAL device code flow → access token
       │
       └─ POST /users/harshit.thakkar@qubecinema.com/calendar/events
            (one request per event)
```

The scraper uses three strategies in order of specificity:

1. **Structured table** – looks for an HTML `<table>` where rows contain time
   and title cells.
2. **Day sections** – finds day-heading elements (`Monday, March 31`, …) and
   collects the sessions listed beneath each heading.
3. **Fallback** – scans every text node for AM/PM time patterns and treats the
   surrounding text as the event title.
