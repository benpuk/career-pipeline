# Job Application Tracker App

This folder contains the local Python web app for Job Application Tracker.

Run locally:

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:8765
```

Configuration lives in `app_config.py`. The app starts with an empty local SQLite database unless `enableDemoData` is set to `True`.

Runtime databases, exports, screenshots, backups, and imported tracker files are intentionally ignored by Git. Do not commit real job application data.

See the repository-level `README.md` and `LICENSE` for release, configuration, ghosting logic, data protection, and licence details.
