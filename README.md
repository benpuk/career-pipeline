# Career Pipeline

Track applications, interviews, ghosting, and job-search progress with clarity.

Career Pipeline is a lightweight local job-search tracking system for individual professionals. It is designed to feel calm, fast, private, and easy to scan while still giving useful pipeline analytics.

It is not an applicant tracking system, hiring platform, social platform, automation tool, or resume-spam workflow.

## Screenshots

Screenshots should be added to `docs/screenshots/` using fictional demo data only.

Suggested captures:

- dashboard overview
- applications table
- application detail view
- add/edit role form

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

Suggested GitHub topics:

- `career-pipeline`
- `job-search`
- `analytics`
- `productivity`
- `workflow`
- `career-tools`

Do not add `react` or `nextjs` topics unless the frontend is migrated to those technologies.

## Roadmap

- Improve empty-state onboarding and first-run guidance.
- Add a focused follow-up queue.
- Split closed ghosted outcomes from active ghosting risk in charts where helpful.
- Add response-time and interview-conversion trend views.
- Add demo screenshots using fictional data.
- Add lightweight tests for status and ghosting rules.
- Explore a hosted version later without changing the local-first product.

## Contributing

See `CONTRIBUTING.md`.

Keep contributions lightweight, privacy-conscious, and focused on individual job seekers. Avoid adding authentication, social features, heavy integrations, or recruiting workflows.

## Licence

This project uses a custom Personal Use Only Licence.

Personal and private use by individuals is allowed. Commercial use is not allowed without written permission from the owner. Recruiters, job boards, agencies, commercial platforms, and paid services may not use, host, resell, rebrand, integrate, or redistribute the app without a separate commercial licence.

See `LICENSE` for the full terms.
