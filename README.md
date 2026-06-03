# Career Pipeline

[![Build](https://img.shields.io/badge/build-npm%20run%20build-2563eb)](#build-and-checks)
[![Licence](https://img.shields.io/badge/licence-personal%20use%20only-475569)](LICENSE)
[![Local first](https://img.shields.io/badge/local--first-privacy--friendly-1f7a4c)](#runtime-data-and-privacy)

Track applications, interviews, ghosting, and job-search progress with clarity.

Career Pipeline is a lightweight local job-search tracking system for individual professionals. It is designed to feel calm, fast, private, and easy to scan while still giving useful pipeline analytics.

It is not an applicant tracking system, hiring platform, social platform, automation tool, or resume-spam workflow.

## Screenshots

Screenshots should be added to `docs/screenshots/` using fictional demo data only.

| Screenshot | Purpose | Status |
| --- | --- | --- |
| Dashboard overview | Show pipeline health, response rate, interview conversion, and ghosting risk. | Placeholder |
| Active pipeline | Show the applications table and follow-up workflow. | Placeholder |
| Ghosted applications | Show how ghosting risk and closed ghosted outcomes are separated. | Placeholder |
| Analytics view | Show route, role type, ageing, and trend panels. | Placeholder |
| Mobile layout | Show the app remains usable on narrow screens. | Placeholder |
| Empty state | Show first-run onboarding with no real data. | Placeholder |

Do not commit screenshots that contain real company names, contact names, salaries, notes, URLs, emails, phone numbers, or browser storage.

## Features

- Track applications, statuses, dates, fit score, follow-ups, contacts, notes, and outcomes.
- View a dashboard for active applications, interview progress, ghosting risk, response rate, conversion rate, and pipeline health.
- Review priority follow-ups based on fit, age, due dates, and ghosting risk.
- Track interview notes and timeline events.
- Export CSV when enabled.
- Run locally with SQLite.
- Start empty by default.
- Optionally seed fictional demo data for review or screenshots.

## Project Structure

```text
app/                         Local Python web app
app/static/                  HTML, CSS, and browser JavaScript
docs/                        Public-readiness notes and screenshot guidance
scripts/                     Small npm wrappers for local Python commands
PUBLIC_RELEASE_CHECKLIST.md  Final checklist before promoting the repo
```

## Local Setup

### Prerequisites

- Node.js 20 or newer
- npm
- Python 3.10 or newer

The npm scripts wrap the lightweight Python local app. There is no installer, desktop shell, hosted service, authentication layer, or heavy backend framework.

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

Run directly with Python:

```bash
python3 app/app.py
```

Use another port or host:

```bash
PORT=9000 HOST=127.0.0.1 npm run dev
```

### Build And Checks

```bash
npm run build
npm run lint
```

These scripts currently verify that the Python source compiles.

### Optional Docker

Docker support is included for simple local review:

```bash
docker compose up
```

Then open:

```text
http://127.0.0.1:8765
```

Docker stores runtime SQLite data in the `career_pipeline_data` volume.

## Configuration

Main configuration lives in:

```text
app/app_config.py
```

Safe environment placeholders are documented in:

```text
.env.example
```

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

When enabled, demo mode loads fictional sample data only. Demo companies include Northstar Digital, FutureStack, BluePeak Systems, Atlas Cloud, and Vertex Dynamics.

Do not enable demo data in a local database that already contains real records unless you are comfortable mixing fake and real records locally.

## Ghosting Logic

- There is only one `Ghosted` status.
- Applications remain `In Progress` until they have had 21 or more days without contact.
- The ghosting counter uses `last_contact_date` if present, otherwise `date_applied`.
- Any contact, such as a holding update, delay notice, contact reply, or interview update, should update `last_contact_date` and restart the counter.
- `Ghosted` is a closed outcome unless the application is reopened.
- `Rejected`, `Rejected Post Interview`, `Withdrawn`, and `Offer Accepted` are closed outcomes.
- There is no separate suggested ghosting status.

## Runtime Data And Privacy

The local database is created at:

```text
app/data/career_pipeline.sqlite3
```

The `data/` folder is ignored by Git and must not be committed.

Do not commit:

- SQLite databases
- `.env` files
- CSV exports
- workbook exports or backups
- screenshots containing personal information
- browser storage exports
- cached application data

Copy `.env.example` to `.env` only for local experimentation. Do not commit `.env`.

## Repository Topics

Recommended GitHub metadata:

```text
Description: Lightweight local job-search tracker for applications, interviews, ghosting, and pipeline health.
```

Suggested topics:

- `career-pipeline`
- `job-search`
- `analytics`
- `productivity`
- `workflow`
- `career-tools`
- `react`
- `nextjs`

Note: the current implementation is plain Python, HTML, CSS, and JavaScript. Keep `react` and `nextjs` only if you intentionally want topic discoverability for a future migration; remove them if you prefer strict technology accuracy.

## Roadmap

Near-term:

- Add demo screenshots using fictional data.
- Add lightweight tests for status and ghosting rules.
- Improve mobile layout polish after manual viewport testing.
- Add local backup and import guidance.

Product improvements:

- Improve analytics for response time, interview conversion, and rejection trends.
- Add configurable ghosting thresholds in the UI.
- Add a focused follow-up queue.
- Improve reminders and follow-up tracking.

Keep avoiding:

- AI features
- recruiter integrations
- enterprise workflows
- social features
- hosted architecture until the local-first product is excellent

## Contributing

See `CONTRIBUTING.md`.

Keep contributions lightweight, privacy-conscious, and focused on individual job seekers. Avoid adding authentication, social features, heavy integrations, or recruiting workflows.

## Licence

This project uses a custom Personal Use Only Licence.

Personal and private use by individuals is allowed. Commercial use is not allowed without written permission from the owner. Recruiters, job boards, agencies, commercial platforms, and paid services may not use, host, resell, rebrand, integrate, or redistribute the app without a separate commercial licence.

This repository is source-available, but it is not open-source in the OSI sense because commercial use is restricted.

See `LICENSE` for the full terms.
