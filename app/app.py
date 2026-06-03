#!/usr/bin/env python3
import csv
import io
import json
import os
import re
import sqlite3
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app_config import (
    ACTIVE_STATUSES,
    APP_CONFIG,
    CLOSED_STATUSES,
    CV_ROUTES,
    DEFAULT_STATUS,
    GHOSTING_THRESHOLD_DAYS,
    INTERVIEW_STATUSES,
    LEGACY_STATUS_MAP,
    STATUSES,
)
from demo_data import DEMO_APPLICATIONS

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "career_pipeline.sqlite3"
STATIC_DIR = BASE_DIR / "static"

ROLE_TYPE_RULES = [
    ("SAP AMS", r"\b(?:ams|sap support)\b"),
    ("Customer Success", r"\b(?:customer success|customer experience|customer excellence|customer operations|client services|customer solutions|onboarding)\b"),
    ("ITSM", r"\b(?:itsm|it service|service manager|service operations|service readiness|application support|support manager|head of support|group it manager)\b"),
    ("Professional Services", r"\b(?:professional services|proserve|practice manager|engagement manager|services engagement|services project|services delivery)\b"),
    ("Implementation", r"\b(?:implementation|implementations|technical implementation)\b"),
    ("Transformation", r"\b(?:transformation|change delivery|business change|operating model)\b"),
    ("Delivery", r"\b(?:delivery|programme|program|project|pmo|portfolio|product)\b"),
    ("Operations", r"\b(?:operations|governance|supplier|vendor|commercial|digital systems)\b"),
    ("SAP / ERP", r"\b(?:sap|erp|s/4hana)\b"),
]


def today_iso():
    return date.today().isoformat()


def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    try:
        serial = int(float(value))
    except ValueError:
        return None
    if 30000 <= serial <= 60000:
        return date.fromordinal(serial + 693594)
    return None


def days_between(start, end=None):
    start_date = parse_date(start)
    end_date = parse_date(end) or date.today()
    if not start_date:
        return 0
    return max((end_date - start_date).days, 0)


def clean_int(value, default=0):
    if value in (None, ""):
        return default
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else default


def clean_fit(value):
    if value in (None, ""):
        return None
    raw = str(value).strip().replace("%", "")
    try:
        num = float(raw)
    except ValueError:
        return None
    if 0 < num <= 1:
        num = num * 5
    if num > 5:
        num = round(num / 20, 1)
    return round(min(max(num, 1), 5), 1)


def is_active(status):
    return status in ACTIVE_STATUSES


def suggested_status(row):
    return ""


def is_ghosting_risk(row):
    # Ghosting review is a recommendation only. It never creates a second
    # status, and any recorded contact restarts the 21-day counter.
    if row["status"] != DEFAULT_STATUS:
        return False
    last_touch = row["last_contact_date"] or row["date_applied"]
    return days_between(last_touch) >= GHOSTING_THRESHOLD_DAYS


def active_days(row):
    if row["status"] in CLOSED_STATUSES:
        return days_between(row["date_applied"], row["outcome_date"] or row["last_contact_date"])
    return days_between(row["date_applied"])


def ageing_bucket(days):
    if days <= 7:
        return "0-7 days"
    if days <= 14:
        return "8-14 days"
    if days <= 21:
        return "15-21 days"
    return "22+ days"


def role_type_for(row):
    text = " ".join(
        str(row.get(field) or "")
        for field in ("company", "role_title", "tags", "notes", "job_description")
    ).lower()
    for label, pattern in ROLE_TYPE_RULES:
        if re.search(pattern, text):
            return label
    return "Uncategorised"


def row_to_dict(row):
    data = dict(row)
    data["days_active"] = active_days(data)
    data["suggested_status"] = suggested_status(data)
    data["ghosting_risk"] = is_ghosting_risk(data)
    data["ageing_bucket"] = ageing_bucket(data["days_active"])
    data["is_active"] = is_active(data["status"])
    data["role_type"] = role_type_for(data)
    return data


def db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role_title TEXT NOT NULL,
                date_applied TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'In Progress',
                cv_route TEXT,
                fit_score REAL,
                salary TEXT,
                location TEXT,
                work_mode TEXT,
                travel_requirement TEXT,
                source TEXT,
                job_url TEXT,
                contact_name TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                job_description TEXT,
                cover_letter TEXT,
                notes TEXT,
                rejection_reason TEXT,
                follow_up_date TEXT,
                next_action TEXT,
                tags TEXT,
                last_contact_date TEXT,
                outcome_date TEXT,
                contact_led INTEGER NOT NULL DEFAULT 0,
                contract_flag INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                stage_name TEXT NOT NULL,
                scheduled_at TEXT,
                interviewer_names TEXT,
                interviewer_emails TEXT,
                meeting_link TEXT,
                prep_notes TEXT,
                questions_asked TEXT,
                feedback TEXT,
                outcome TEXT,
                follow_up_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            );

            CREATE TABLE IF NOT EXISTS timeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                event_date TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            );
            """
        )
    seed_demo_data()


def seed_demo_data():
    if not APP_CONFIG["features"]["enableDemoData"]:
        return
    with db() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    if existing:
        return
    for item in DEMO_APPLICATIONS:
        create_application(item)


APPLICATION_FIELDS = [
    "company",
    "role_title",
    "date_applied",
    "status",
    "cv_route",
    "fit_score",
    "salary",
    "location",
    "work_mode",
    "travel_requirement",
    "source",
    "job_url",
    "contact_name",
    "contact_email",
    "contact_phone",
    "job_description",
    "cover_letter",
    "notes",
    "rejection_reason",
    "follow_up_date",
    "next_action",
    "tags",
    "last_contact_date",
    "outcome_date",
    "contact_led",
    "contract_flag",
]


def normalize_payload(payload):
    data = {field: payload.get(field, "") for field in APPLICATION_FIELDS}
    data["company"] = data["company"].strip()
    data["role_title"] = data["role_title"].strip()
    data["date_applied"] = data["date_applied"] or today_iso()
    data["status"] = normalize_status(data["status"])
    data["fit_score"] = clean_fit(data["fit_score"])
    data["contact_led"] = 1 if str(data["contact_led"]).lower() in {"1", "true", "yes", "on"} else 0
    data["contract_flag"] = 1 if str(data["contract_flag"]).lower() in {"1", "true", "yes", "on"} else 0
    if data["status"] in CLOSED_STATUSES and not data["outcome_date"]:
        data["outcome_date"] = data["last_contact_date"] or today_iso()
    return data


def normalize_status(status):
    status = (status or "").strip()
    status = LEGACY_STATUS_MAP.get(status, status)
    return status if status in STATUSES else DEFAULT_STATUS


def create_application(payload):
    data = normalize_payload(payload)
    if not data["company"] or not data["role_title"]:
        raise ValueError("Company and role title are required.")
    placeholders = ", ".join("?" for _ in APPLICATION_FIELDS)
    with db() as conn:
        cur = conn.execute(
            f"INSERT INTO applications ({', '.join(APPLICATION_FIELDS)}) VALUES ({placeholders})",
            [data[field] for field in APPLICATION_FIELDS],
        )
        app_id = cur.lastrowid
        conn.execute(
            "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
            (app_id, data["date_applied"], "Applied", f"Applied for {data['role_title']} at {data['company']}"),
        )
    return app_id


def update_application(app_id, payload):
    data = normalize_payload(payload)
    assignments = ", ".join(f"{field}=?" for field in APPLICATION_FIELDS)
    with db() as conn:
        before = conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
        if not before:
            raise ValueError("Application not found.")
        conn.execute(
            f"UPDATE applications SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [data[field] for field in APPLICATION_FIELDS] + [app_id],
        )
        if before["status"] != data["status"]:
            conn.execute(
                "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
                (app_id, data["last_contact_date"] or today_iso(), "Status Change", f"{before['status']} -> {data['status']}"),
            )


def list_applications(filters=None):
    filters = filters or {}
    sql = "SELECT * FROM applications"
    clauses = []
    params = []
    query = filters.get("q", "").strip()
    if query:
        clauses.append("(company LIKE ? OR role_title LIKE ? OR notes LIKE ? OR tags LIKE ?)")
        params.extend([f"%{query}%"] * 4)
    if filters.get("status"):
        clauses.append("status=?")
        params.append(filters["status"])
    if filters.get("cv_route"):
        clauses.append("cv_route=?")
        params.append(filters["cv_route"])
    if filters.get("active") == "1":
        clauses.append("status NOT IN ({})".format(",".join("?" for _ in CLOSED_STATUSES)))
        params.extend(sorted(CLOSED_STATUSES))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY date_applied DESC, id DESC"
    with db() as conn:
        return [row_to_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_application(app_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            return None
        interviews = [dict(item) for item in conn.execute("SELECT * FROM interviews WHERE application_id=? ORDER BY scheduled_at DESC, id DESC", (app_id,))]
        timeline = [dict(item) for item in conn.execute("SELECT * FROM timeline_events WHERE application_id=? ORDER BY event_date DESC, id DESC", (app_id,))]
    data = row_to_dict(row)
    data["interviews"] = interviews
    data["timeline"] = timeline
    return data


def forecast_for(row):
    fit = row["fit_score"] or 3
    days = active_days(row)
    status = row["status"]
    interview = 0.10 + (fit - 1) * 0.08
    offer = 0.02 + (fit - 1) * 0.015
    ghost = 0.12 + min(days, 28) * 0.012
    if status in INTERVIEW_STATUSES:
        interview = 0.65
        offer += 0.08
        ghost = max(ghost - 0.08, 0.05)
    if days >= GHOSTING_THRESHOLD_DAYS and status == DEFAULT_STATUS:
        ghost += 0.20
    rejection = max(0.05, 1 - interview - offer - ghost)
    total = interview + rejection + offer + ghost
    return {
        "interview": interview / total,
        "rejection": rejection / total,
        "offer": offer / total,
        "ghosted": ghost / total,
    }


def performance_row(label_key, label, bucket_apps):
    count = len(bucket_apps)
    fit_scores = [app["fit_score"] for app in bucket_apps if app["fit_score"] is not None]
    interviews = sum(1 for app in bucket_apps if app["status"] in INTERVIEW_STATUSES)
    rejections = sum(1 for app in bucket_apps if app["status"] in {"Rejected", "Rejected Post Interview"})
    ghosts = sum(1 for app in bucket_apps if app["status"] == "Ghosted" or is_ghosting_risk(app))
    offers = sum(1 for app in bucket_apps if app["status"] in {"Offer Pending", "Offer Accepted"})
    return {
        label_key: label,
        "applications": count,
        "avg_fit": round(sum(fit_scores) / len(fit_scores), 1) if fit_scores else 0,
        "interview_rate": round(interviews / count * 100, 1) if count else 0,
        "rejection_rate": round(rejections / count * 100, 1) if count else 0,
        "ghosting_rate": round(ghosts / count * 100, 1) if count else 0,
        "traction": round((interviews + offers * 2) / count * 100, 1) if count else 0,
    }


def dashboard_data():
    apps = list_applications()
    active = [app for app in apps if app["is_active"]]
    total = len(apps)
    interviews = sum(1 for app in apps if app["status"] in INTERVIEW_STATUSES)
    rejections = sum(1 for app in apps if app["status"] == "Rejected")
    post_interview = sum(1 for app in apps if app["status"] == "Rejected Post Interview")
    ghosted = sum(1 for app in apps if app["status"] == "Ghosted")
    ghosting_risk = sum(1 for app in active if is_ghosting_risk(app))
    offers = sum(1 for app in apps if app["status"] in {"Offer Pending", "Offer Accepted"})
    responded = sum(1 for app in apps if app["last_contact_date"] and days_between(app["date_applied"], app["last_contact_date"]) > 0)
    this_week = sum(1 for app in apps if days_between(app["date_applied"]) <= date.today().weekday())
    avg_active = round(sum(app["days_active"] for app in active) / len(active), 1) if active else 0

    status_breakdown = {status: 0 for status in STATUSES}
    for app in apps:
        status_breakdown[app["status"]] = status_breakdown.get(app["status"], 0) + 1

    ageing = {"0-7 days": 0, "8-14 days": 0, "15-21 days": 0, "22+ days": 0}
    for app in active:
        ageing[app["ageing_bucket"]] += 1

    weekly = {}
    for app in apps:
        applied = parse_date(app["date_applied"])
        if not applied:
            continue
        monday = applied.fromordinal(applied.toordinal() - applied.weekday())
        label = monday.isoformat()
        weekly[label] = weekly.get(label, 0) + 1
    weekly_rows = [{"week": key, "applications": weekly[key], "target": 25} for key in sorted(weekly)[-8:]]

    route_rows = [
        performance_row("route", route, [app for app in apps if app["cv_route"] == route])
        for route in CV_ROUTES
    ]
    best_route = max(route_rows, key=lambda row: row["traction"], default=None)

    role_types = sorted({app["role_type"] for app in apps})
    role_type_rows = [
        performance_row("role_type", role_type, [app for app in apps if app["role_type"] == role_type])
        for role_type in role_types
    ]
    role_type_rows.sort(key=lambda row: (row["role_type"] == "Uncategorised", -row["applications"], row["role_type"]))

    forecast = {"interview": 0, "rejection": 0, "offer": 0, "ghosted": 0}
    for app in active:
        weights = forecast_for(app)
        for key, value in weights.items():
            forecast[key] += value
    forecast_rows = []
    for key, value in forecast.items():
        forecast_rows.append({
            "outcome": key.title(),
            "expected": round(value, 1),
            "percent": round((value / len(active) * 100), 1) if active else 0,
        })

    followups = []
    for app in active:
        if app["status"] in CLOSED_STATUSES:
            continue
        fit = app["fit_score"] or 0
        next_age = days_between(app["follow_up_date"], today_iso()) if app["follow_up_date"] else 0
        score = fit * 20 + min(app["days_active"], 30) + max(next_age, 0) * 3
        action = app["next_action"] or ("Follow up now" if app["days_active"] >= 7 else "Monitor")
        if is_ghosting_risk(app):
            action = "Review and decide whether to mark ghosted"
        followups.append({
            "id": app["id"],
            "company": app["company"],
            "role_title": app["role_title"],
            "days_active": app["days_active"],
            "status": app["status"],
            "fit_score": app["fit_score"],
            "suggested_action": action,
            "priority_score": round(score, 1),
        })
    followups.sort(key=lambda item: item["priority_score"], reverse=True)

    return {
        "kpis": {
            "total": total,
            "active": len(active),
            "rejections": rejections,
            "ghosted": ghosted,
            "ghosting_risk": ghosting_risk,
            "interviews": interviews,
            "post_interview_rejections": post_interview,
            "offers": offers,
            "applications_this_week": this_week,
            "average_days_active": avg_active,
            "pipeline_health": round((len(active) / total * 100), 1) if total else 0,
            "response_rate": round((responded / total * 100), 1) if total else 0,
            "interview_conversion_rate": round((interviews / total * 100), 1) if total else 0,
        },
        "weekly": weekly_rows,
        "status_breakdown": [{"label": key, "value": value} for key, value in status_breakdown.items()],
        "ageing": [{"label": key, "value": value} for key, value in ageing.items()],
        "cv_routes": route_rows,
        "role_types": role_type_rows,
        "best_route": best_route,
        "forecast": forecast_rows,
        "priority_followups": followups[:12],
    }


def import_csv_text(text):
    reader = csv.DictReader(io.StringIO(text))
    count = 0
    for raw in reader:
        payload = {
            "company": raw.get("Company") or raw.get("company") or "",
            "role_title": raw.get("Title") or raw.get("Role") or raw.get("role_title") or "",
            "date_applied": raw.get("Date Applied") or raw.get("Date") or raw.get("date_applied") or today_iso(),
            "status": raw.get("Stage") or raw.get("Status") or raw.get("status") or DEFAULT_STATUS,
            "cv_route": raw.get("Best CV Route") or raw.get("CV Route") or raw.get("cv_route") or "",
            "fit_score": raw.get("Market Fit %") or raw.get("Fit Score") or raw.get("fit_score") or "",
            "salary": raw.get("Salary") or raw.get("salary") or "",
            "location": raw.get("Location/Remote") or raw.get("Location") or raw.get("location") or "",
            "source": raw.get("Source") or raw.get("source") or "",
            "job_url": raw.get("Application URL") or raw.get("Job URL") or raw.get("job_url") or "",
            "notes": raw.get("Comments") or raw.get("Notes") or raw.get("notes") or "",
            "follow_up_date": raw.get("Follow-up Date") or raw.get("follow_up_date") or "",
            "next_action": raw.get("Next Action") or raw.get("next_action") or "",
            "last_contact_date": raw.get("Last Update") or raw.get("last_contact_date") or "",
        }
        if payload["company"] and payload["role_title"]:
            create_application(payload)
            count += 1
    return count


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.serve_file(STATIC_DIR / "index.html", "text/html")
        if parsed.path.startswith("/static/"):
            return self.serve_file(STATIC_DIR / parsed.path.replace("/static/", "", 1))
        if parsed.path == "/api/config":
            public_config = dict(APP_CONFIG)
            public_config["statuses"] = {
                **APP_CONFIG["statuses"],
                "all": STATUSES,
            }
            return self.send_json(public_config)
        if parsed.path == "/api/options":
            return self.send_json({"statuses": STATUSES, "cv_routes": CV_ROUTES})
        if parsed.path == "/api/dashboard":
            return self.send_json(dashboard_data())
        if parsed.path == "/api/applications":
            return self.send_json(list_applications({key: values[0] for key, values in parse_qs(parsed.query).items()}))
        if parsed.path.startswith("/api/applications/"):
            app_id = clean_int(parsed.path.rsplit("/", 1)[-1])
            item = get_application(app_id)
            return self.send_json(item if item else {"error": "Not found"}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        if parsed.path == "/export/applications.csv":
            return self.export_applications_csv()
        return self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/applications":
            try:
                app_id = create_application(self.read_json())
                return self.send_json({"id": app_id}, HTTPStatus.CREATED)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if parsed.path == "/api/import/csv":
            if not APP_CONFIG["features"]["enableCsvImport"]:
                return self.send_json({"error": "CSV import is disabled by configuration."}, HTTPStatus.FORBIDDEN)
            text = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
            count = import_csv_text(text)
            return self.send_json({"imported": count})
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/interviews"):
            app_id = clean_int(parsed.path.split("/")[-2])
            payload = self.read_json()
            with db() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO interviews (
                        application_id, stage_name, scheduled_at, interviewer_names, interviewer_emails,
                        meeting_link, prep_notes, questions_asked, feedback, outcome, follow_up_sent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        app_id,
                        payload.get("stage_name", "Interview"),
                        payload.get("scheduled_at", ""),
                        payload.get("interviewer_names", ""),
                        payload.get("interviewer_emails", ""),
                        payload.get("meeting_link", ""),
                        payload.get("prep_notes", ""),
                        payload.get("questions_asked", ""),
                        payload.get("feedback", ""),
                        payload.get("outcome", ""),
                        1 if payload.get("follow_up_sent") else 0,
                    ),
                )
                conn.execute(
                    "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
                    (app_id, payload.get("scheduled_at", today_iso())[:10] or today_iso(), "Interview", payload.get("stage_name", "Interview")),
                )
            return self.send_json({"id": cur.lastrowid}, HTTPStatus.CREATED)
        return self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/applications/"):
            app_id = clean_int(parsed.path.rsplit("/", 1)[-1])
            try:
                update_application(app_id, self.read_json())
                return self.send_json({"ok": True})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        return self.send_error(HTTPStatus.NOT_FOUND)

    def serve_file(self, path, content_type=None):
        if not path.exists() or not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        content_type = content_type or ("text/css" if path.suffix == ".css" else "application/javascript" if path.suffix == ".js" else "application/octet-stream")
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def export_applications_csv(self):
        if not APP_CONFIG["features"]["enableCsvExport"]:
            return self.send_json({"error": "CSV export is disabled by configuration."}, HTTPStatus.FORBIDDEN)
        apps = list_applications()
        output = io.StringIO()
        fields = ["id"] + APPLICATION_FIELDS + ["days_active", "suggested_status", "ageing_bucket"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for app in apps:
            writer.writerow({field: app.get(field, "") for field in fields})
        body = output.getvalue().encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", "attachment; filename=career_pipeline_export.csv")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    init_db()
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Job tracker running at http://{host}:{port}")
    print(f"Database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
