# Job Application Tracker

A lightweight private web app for managing job applications, follow-ups, ghosting, interviews, rejections, and pipeline health.

This repository is prepared for a private GitHub release. It should remain private unless the owner chooses otherwise.

## What The App Does

- Tracks job applications, status, dates, fit score, notes, follow-ups, contacts, and outcomes.
- Shows dashboard KPIs, weekly trends, status breakdown, active ageing, route performance, and priority follow-ups.
- Stores runtime data locally in SQLite.
- Exports application data to CSV when enabled.
- Starts empty by default so real application data is not committed.
- Can optionally seed fictional demo data for screenshots or portfolio review.

## Key Features

- Application list with search and status filters.
- Application detail view with contact, timeline, notes, job description, and interview sections.
- Dashboard with active, closed, interview, rejection, ghosting, and pipeline-health metrics.
- Ghosting counter based on last contact or date applied.
- CSV export controlled by config.
- CSV import endpoint is disabled by default for a safer private release.

## Local Setup

### Prerequisites

- Node.js 20 or newer
- npm
- Python 3.10 or newer

The npm scripts intentionally wrap the lightweight Python local app. There is no Electron, Tauri, hosted backend, authentication layer, or SaaS packaging.

### Install

```bash
npm install
```

### Run Locally

```bash
npm run dev
```

Open:

```text
http://127.0.0.1:8765
```

You can still run the Python app directly:

```bash
python3 local-job-crm/app.py
```

Use another port or host:

```bash
PORT=9000 HOST=127.0.0.1 npm run dev
```

### Build And Checks

This project does not require a frontend build step. The build script verifies the Python source compiles:

```bash
npm run build
```

The lint script currently performs the same lightweight Python compile check:

```bash
npm run lint
```

### Optional Docker

Docker support is included for simple local review:

```bash
docker compose up
```

Then open:

```text
http://127.0.0.1:8765
```

Docker stores the runtime SQLite database in the `job_tracker_data` volume.

### Runtime Data

The local database is created at:

```text
local-job-crm/data/job_tracker.sqlite3
```

The `data/` folder is ignored by Git and must not be committed.

## Configuration

Configuration lives in:

```text
local-job-crm/app_config.py
```

Safe environment placeholders are documented in:

```text
.env.example
```

The config controls:

- app name, description, owner, and copyright year
- ghosting threshold, currently 21 days
- warning threshold, currently 14 days
- active, closed, and default statuses
- date display format and default currency
- local/browser storage key names for future client-side use
- feature flags for demo data, CSV export, CSV import, analytics, and commercial branding
- licence metadata

Supported environment overrides:

- `NEXT_PUBLIC_APP_NAME`
- `NEXT_PUBLIC_ENABLE_DEMO_DATA`
- `NEXT_PUBLIC_DEFAULT_CURRENCY`
- `NEXT_PUBLIC_GHOSTING_THRESHOLD_DAYS`
- `PORT`
- `HOST`

Demo data is disabled by default:

```python
"enableDemoData": False
```

If enabled, only fictional records are loaded, using companies such as Acme Technologies, Northstar Digital, FutureStack, and BluePeak Systems.

Do not enable demo data in a database that already contains real application records unless you are comfortable mixing fake and real records locally.

## Ghosting Logic

There is only one `Ghosted` status.

Applications remain `In Progress` until they have had 21 or more days without contact. The app can then recommend reviewing the application for ghosting or show it as ghosting-risk, depending on configuration and UI behavior.

The ghosting counter uses:

```text
last_contact_date if present, otherwise date_applied
```

If contact is received, such as a holding email, delay update, recruiter reply, or interview update, update `last_contact_date`. The role remains or returns to `In Progress`, and the counter restarts.

`Rejected`, `Rejected Post Interview`, `Ghosted`, `Withdrawn`, and `Offer Accepted` are closed outcomes. A `Ghosted` role can be reopened if contact later resumes.

## Data Protection

Do not commit:

- SQLite databases
- `.env` files
- CSV exports
- workbook exports or backups
- screenshots containing application data
- browser storage exports
- cached application state

The repository `.gitignore` blocks those artifacts by default.

Copy `.env.example` to `.env` only for local experimentation. Do not commit `.env`.

## Licence

This project uses a custom Personal Use Only Licence.

Personal and private use by individuals is allowed. Commercial use is not allowed without written permission from the owner. Companies, recruiters, job boards, agencies, SaaS providers, and commercial platforms may not use, host, resell, rebrand, integrate, or redistribute the app without a separate commercial licence.

See [LICENSE](LICENSE) for the full terms.

## Private Release Note

Create the GitHub repository as private. Do not publish this repository publicly unless you have reviewed the code, data, screenshots, exports, and licence terms again.
