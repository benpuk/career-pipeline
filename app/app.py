#!/usr/bin/env python3
import base64
import csv
import io
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = Path.home() / "Library" / "Application Support" / "Job Application Tracker" / "data"
DATA_DIR = Path(os.environ.get("JOB_TRACKER_DATA_DIR") or (DEFAULT_DATA_DIR if DEFAULT_DATA_DIR.exists() else BASE_DIR / "data"))
DB_PATH = DATA_DIR / "job_tracker.sqlite3"
STATIC_DIR = BASE_DIR / "static"
ATTACHMENTS_DIR = DATA_DIR / "attachments"

STATUSES = [
    "In Progress",
    "Interview",
    "Rejection",
    "Rejection Post Interview",
    "Ghosted",
    "Offer",
    "Withdrawn",
]

INTERVIEW_STAGE_OPTIONS = [
    "",
    "Screening",
    "Stage 1",
    "Stage 2",
    "Stage 3",
]

CV_ROUTES = [
    "CV1 SAP / ERP",
    "CV2 Service Delivery",
    "CV3 Governance / Operations",
]

ROLE_TYPES = [
    "SAP AMS",
    "Delivery",
    "Transformation",
    "Customer Success",
    "ITSM",
    "Operations",
    "Implementation",
    "PMO",
    "Product",
    "AI",
    "SaaS",
    "Professional Services",
    "SAP / ERP",
]

ROLE_TYPE_RULES = [
    ("SAP AMS", r"\b(?:ams|sap support)\b"),
    ("Customer Success", r"\b(?:customer success|customer experience|customer excellence|customer operations|client services|customer solutions|onboarding)\b"),
    ("ITSM", r"\b(?:itsm|it service|service manager|service operations|service readiness|application support|support manager|head of support|head of service|group it manager)\b"),
    ("Professional Services", r"\b(?:professional services|proserve|practice manager|engagement manager|services engagement|services project|services delivery)\b"),
    ("Implementation", r"\b(?:implementation|implementations|technical implementation)\b"),
    ("Transformation", r"\b(?:transformation|change delivery|business change|operating model)\b"),
    ("AI", r"\b(?:openai|ai|ml|artificial intelligence)\b"),
    ("Delivery", r"\b(?:delivery|programme|program|project|pmo|portfolio|product)\b"),
    ("Operations", r"\b(?:operations|governance|supplier|vendor|commercial|digital systems)\b"),
    ("SAP / ERP", r"\b(?:sap|erp|s/4hana)\b"),
]

SOURCES = ["LinkedIn", "Recruiter", "Direct company site", "Referral", "Job board"]
WORK_MODES = ["Remote", "Hybrid", "Onsite"]
TRAVEL_REQUIREMENTS = ["None", "Occasional", "Regular", "High", "Unknown"]

REJECTION_REASONS = [
    "Not recorded",
    "Immediate Rejection (0-2 days)",
    "Better matched candidates",
    "Insufficient experience",
    "Skills mismatch",
    "Location / working pattern",
    "Salary / level mismatch",
    "Security clearance / eligibility",
    "Role closed / hiring paused",
    "No response / ghosted",
    "No longer interested",
    "Other",
]

CLOSED_STATUSES = {"Rejection", "Rejection Post Interview", "Ghosted", "Offer", "Withdrawn"}
EMPLOYER_REJECTION_STATUSES = {"Rejection", "Rejection Post Interview"}
OFFER_STATUSES = {"Offer"}
WITHDRAWN_STATUSES = {"Withdrawn"}
ALL_CLOSED_OUTCOME_STATUSES = EMPLOYER_REJECTION_STATUSES | {"Ghosted"} | OFFER_STATUSES | WITHDRAWN_STATUSES
INTERVIEW_STATUSES = {"Interview"}
LEGACY_INTERVIEW_STATUSES = {"Screening Completed", "1st Interview Completed", "2nd Interview Completed"}
DEFAULT_STATUS = "In Progress"
LEGACY_STATUS_MAP = {
    "Rejected": "Rejection",
    "Rejected Post Interview": "Rejection Post Interview",
    "Offer Accepted": "Offer",
    "Offer Pending": "Interview",
    "Rejected by Me": "Withdrawn",
    "User Rejected": "Withdrawn",
    "User Rejection": "Withdrawn",
}
GHOSTING_DAYS = 21


def today_iso():
    return date.today().isoformat()


def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    if "T" in value:
        value = value.split("T", 1)[0]
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


def clean_file_path(value):
    raw = str(value or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1].strip()
    return os.path.expanduser(raw)


def local_file_path(value):
    cleaned = clean_file_path(value)
    if not cleaned:
        return None
    path = Path(cleaned)
    if not path.is_absolute() or not path.exists() or not path.is_file():
        return None
    return path


def safe_filename(value):
    name = Path(str(value or "attachment")).name.strip() or "attachment"
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name or "attachment"


def managed_attachment_path(app_id, filename):
    folder = ATTACHMENTS_DIR / str(app_id)
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem or "attachment"
    suffix = Path(filename).suffix
    candidate = folder / safe_filename(filename)
    counter = 2
    while candidate.exists():
        candidate = folder / safe_filename(f"{stem} ({counter}){suffix}")
        counter += 1
    return candidate


def copy_attachment_to_store(app_id, source):
    source_path = local_file_path(source)
    if not source_path:
        raise ValueError("Attachment file was not found.")
    destination = managed_attachment_path(app_id, source_path.name)
    try:
        shutil.copy2(source_path, destination)
    except PermissionError as exc:
        raise ValueError("macOS blocked access to that file. Use Select file so the browser can attach a managed copy.") from exc
    return destination


def save_uploaded_attachment(app_id, filename, content):
    if not filename or not content:
        raise ValueError("Choose a file or enter a local path before adding a document.")
    raw_content = str(content)
    if "," in raw_content and raw_content.split(",", 1)[0].startswith("data:"):
        raw_content = raw_content.split(",", 1)[1]
    destination = managed_attachment_path(app_id, filename)
    destination.write_bytes(base64.b64decode(raw_content))
    return destination


def normalized_status(status):
    raw = str(status or "").strip()
    if raw in LEGACY_INTERVIEW_STATUSES:
        return "Interview"
    return LEGACY_STATUS_MAP.get(raw, raw)


normalize_status = normalized_status


def normalize_interview_stage(value):
    raw = str(value or "").strip()
    lower = raw.lower()
    if not raw:
        return ""
    if raw in INTERVIEW_STAGE_OPTIONS:
        return raw
    if any(term in lower for term in ["screen", "phone", "recruiter", "hr"]):
        return "Screening"
    if any(term in lower for term in ["3", "third", "final", "panel", "onsite", "on-site"]):
        return "Stage 3"
    if any(term in lower for term in ["2", "second"]):
        return "Stage 2"
    if any(term in lower for term in ["1", "first", "interview", "technical", "hiring manager"]):
        return "Stage 1"
    return raw


def interview_stage_rank(stage):
    normalized = normalize_interview_stage(stage)
    return {
        "Screening": 1,
        "Stage 1": 2,
        "Stage 2": 3,
        "Stage 3": 4,
    }.get(normalized, 0)


def interview_stage_from_rank(rank):
    return {
        1: "Screening",
        2: "Stage 1",
        3: "Stage 2",
        4: "Stage 3",
    }.get(rank, "")


def get_interview_stage(app):
    stage_text = str(app.get("interview_stages") or "")
    rank = 0
    for part in re.split(r"[\n,;/|]+", stage_text):
        rank = max(rank, interview_stage_rank(part))
    return interview_stage_from_rank(rank)


def is_interviewed(app):
    return interview_stage_rank(get_interview_stage(app)) > 0


def get_interview_stage_counts(apps):
    counts = {
        "screening": 0,
        "stage_1": 0,
        "stage_2": 0,
        "stage_3": 0,
    }
    for app in apps:
        rank = interview_stage_rank(get_interview_stage(app))
        if rank >= interview_stage_rank("Screening"):
            counts["screening"] += 1
        if rank >= interview_stage_rank("Stage 1"):
            counts["stage_1"] += 1
        if rank >= interview_stage_rank("Stage 2"):
            counts["stage_2"] += 1
        if rank >= interview_stage_rank("Stage 3"):
            counts["stage_3"] += 1
    return counts


def get_interviewed_application_count(apps):
    return sum(1 for app in apps if is_interviewed(app))


def get_interview_event_count(apps):
    return sum(get_interview_stage_counts(apps).values())


def attach_interview_history(apps, conn=None):
    if not apps:
        return apps
    owns_connection = conn is None
    if owns_connection:
        conn = db()
    try:
        app_ids = [app["id"] for app in apps if app.get("id") is not None]
        if not app_ids:
            return apps
        placeholders = ",".join("?" for _ in app_ids)
        rows = conn.execute(
            f"""
            SELECT application_id, stage_name, scheduled_at
            FROM interviews
            WHERE application_id IN ({placeholders})
            ORDER BY scheduled_at ASC, id ASC
            """,
            app_ids,
        ).fetchall()
    finally:
        if owns_connection:
            conn.close()

    by_app = {app["id"]: {"count": 0, "stages": [], "latest_date": ""} for app in apps if app.get("id") is not None}
    for row in rows:
        item = by_app.get(row["application_id"])
        if item is None:
            continue
        stage = normalize_interview_stage(row["stage_name"])
        item["count"] += 1
        if stage:
            item["stages"].append(stage)
        current = latest_date(item["latest_date"], row["scheduled_at"])
        item["latest_date"] = current.isoformat() if current else item["latest_date"]

    for app in apps:
        item = by_app.get(app.get("id"), {"count": 0, "stages": [], "latest_date": ""})
        app["interview_count"] = item["count"]
        app["interview_stages"] = " | ".join(item["stages"])
        app["latest_interview_date"] = item["latest_date"]
        app["reached_interview_stage"] = get_interview_stage(app)
        app["interview_stage"] = app["reached_interview_stage"]
    return apps


def reached_interview_stage(app):
    return get_interview_stage(app)


def has_interview_reached(app, stage):
    return interview_stage_rank(get_interview_stage(app)) >= interview_stage_rank(stage)


def is_interview_stage(app, stage):
    return get_interview_stage(app) == normalize_interview_stage(stage)


def has_interview_data(app):
    return is_interviewed(app)


def interview_breakdown_counts(apps):
    return get_interview_stage_counts(apps)


def latest_contact_or_applied_date(row):
    dates = [parse_date(row.get("date_applied")), parse_date(row.get("last_contact_date"))]
    dates = [item for item in dates if item]
    return max(dates) if dates else None


def effective_ghosted_date(row):
    latest = latest_contact_or_applied_date(row)
    return latest + timedelta(days=GHOSTING_DAYS) if latest else None


def effective_status(row):
    status = normalized_status(row.get("status"))
    if status == "In Progress":
        latest = latest_contact_or_applied_date(row)
        if latest and (date.today() - latest).days >= GHOSTING_DAYS:
            return "Ghosted"
    return status


def is_active(status):
    return status not in CLOSED_STATUSES


def active_days(row, status=None):
    status = status or effective_status(row)
    if status in CLOSED_STATUSES:
        if row.get("status") == "In Progress" and status == "Ghosted":
            end_date = effective_ghosted_date(row)
            return days_between(row["date_applied"], end_date.isoformat() if end_date else None)
        return days_between(row["date_applied"], row["outcome_date"] or row["last_contact_date"])
    return days_between(row["date_applied"])


def contact_age_days(row, status=None):
    status = status or effective_status(row)
    latest_touch = latest_contact_or_applied_date(row)
    start_date = latest_touch.isoformat() if latest_touch else row["date_applied"]
    if row.get("status") == "In Progress" and status == "Ghosted":
        end_date = effective_ghosted_date(row)
        return days_between(start_date, end_date.isoformat() if end_date else None)
    if status in CLOSED_STATUSES:
        return days_between(start_date, row.get("outcome_date") or row.get("last_contact_date"))
    return days_between(start_date)


def ageing_bucket(days):
    if days <= 7:
        return "0-7 days"
    if days <= 14:
        return "8-14 days"
    if days <= 20:
        return "15-20 days"
    return "21+ days"


def median(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return 0
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return round((values[mid - 1] + values[mid]) / 2, 1)


def infer_role_type(row):
    text = " ".join(
        str(row.get(field) or "")
        for field in ("company", "role_title", "tags", "notes", "job_description")
    ).lower()
    for label, pattern in ROLE_TYPE_RULES:
        if re.search(pattern, text):
            return label
    return ""


def row_to_dict(row):
    data = dict(row)
    data["status"] = normalized_status(data["status"])
    if data["status"] not in STATUSES:
        data["status"] = "In Progress"
    data["role_type"] = (data.get("role_type") or "").strip() or infer_role_type(data)
    data["interview_stage"] = normalize_interview_stage(data.get("interview_stage"))
    data["effective_status"] = effective_status(data)
    ghosted_date = effective_ghosted_date(data) if data["status"] == "In Progress" and data["effective_status"] == "Ghosted" else None
    data["effective_ghosted_date"] = ghosted_date.isoformat() if ghosted_date else ""
    data["days_active"] = active_days(data, data["effective_status"])
    data["days_since_last_contact"] = contact_age_days(data, data["effective_status"])
    data["ageing_bucket"] = ageing_bucket(data["days_since_last_contact"])
    data["is_active"] = is_active(data["effective_status"])
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
                role_type TEXT,
                fit_score REAL,
                salary TEXT,
                location TEXT,
                work_mode TEXT,
                travel_requirement TEXT,
                source TEXT,
                job_url TEXT,
                recruiter_name TEXT,
                contact_email TEXT,
                contact_phone TEXT,
                job_description TEXT,
                cover_letter TEXT,
                notes TEXT,
                rejection_reason TEXT,
                rejection_email TEXT,
                follow_up_date TEXT,
                next_action TEXT,
                tags TEXT,
                attachment_links TEXT,
                last_contact_date TEXT,
                outcome_date TEXT,
                recruiter_led INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                due_date TEXT,
                action TEXT NOT NULL,
                notes TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                path TEXT NOT NULL,
                kind TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(application_id) REFERENCES applications(id)
            );
            """
        )
        ensure_columns(conn)
        migrate_statuses(conn)
        migrate_interview_history(conn)
        migrate_rejection_reasons(conn)


def ensure_columns(conn):
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(applications)").fetchall()}
    additions = {
        "role_type": "TEXT",
        "interview_stage": "TEXT",
        "attachment_links": "TEXT",
        "rejection_email": "TEXT",
        "withdrawal_reason": "TEXT",
    }
    for name, column_type in additions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE applications ADD COLUMN {name} {column_type}")


def migrate_statuses(conn):
    conn.execute(
        "UPDATE applications SET status='Interview' WHERE status IN ({})".format(
            ",".join("?" for _ in LEGACY_INTERVIEW_STATUSES)
        ),
        sorted(LEGACY_INTERVIEW_STATUSES),
    )
    for legacy, current in LEGACY_STATUS_MAP.items():
        conn.execute("UPDATE applications SET status=? WHERE status=?", (current, legacy))


def migrate_interview_history(conn):
    try:
        legacy_rows = conn.execute(
            """
            SELECT id, interview_stage, last_contact_date, date_applied
            FROM applications
            WHERE COALESCE(interview_stage, '')<>''
            """
        ).fetchall()
    except sqlite3.OperationalError:
        legacy_rows = []
    for row in legacy_rows:
        ensure_logged_interview_stage(
            conn,
            row["id"],
            row["interview_stage"],
            row["last_contact_date"] or row["date_applied"],
        )

    try:
        interview_rows = conn.execute("SELECT application_id, stage_name FROM interviews").fetchall()
    except sqlite3.OperationalError:
        interview_rows = []
    reached = {}
    for row in interview_rows:
        stage = normalize_interview_stage(row["stage_name"])
        if not stage:
            continue
        app_id = row["application_id"]
        current = reached.get(app_id, "")
        if interview_stage_rank(stage) > interview_stage_rank(current):
            reached[app_id] = stage
    for app_id, stage in reached.items():
        conn.execute("UPDATE applications SET interview_stage=? WHERE id=?", (stage, app_id))

    conn.execute(
        """
        UPDATE applications
        SET interview_stage=''
        WHERE id NOT IN (SELECT DISTINCT application_id FROM interviews)
          AND COALESCE(interview_stage, '')<>''
        """
    )


def ensure_logged_interview_stage(conn, app_id, stage, scheduled_at=None):
    normalized_stage = normalize_interview_stage(stage)
    if not normalized_stage:
        return
    rows = conn.execute("SELECT stage_name FROM interviews WHERE application_id=?", (app_id,)).fetchall()
    current_rank = max((interview_stage_rank(row["stage_name"]) for row in rows), default=0)
    if current_rank >= interview_stage_rank(normalized_stage):
        return
    event_date = (scheduled_at or today_iso())[:10] or today_iso()
    conn.execute(
        """
        INSERT INTO interviews (
            application_id, stage_name, scheduled_at, interviewer_names, interviewer_emails,
            meeting_link, prep_notes, questions_asked, feedback, outcome, follow_up_sent
        ) VALUES (?, ?, ?, '', '', '', '', '', '', '', 0)
        """,
        (app_id, normalized_stage, event_date),
    )
    conn.execute(
        "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
        (app_id, event_date, "Interview", normalized_stage),
    )


def interview_payload(payload):
    return {
        "stage_name": normalize_interview_stage(payload.get("stage_name", "Interview")),
        "scheduled_at": payload.get("scheduled_at", ""),
        "interviewer_names": payload.get("interviewer_names", ""),
        "interviewer_emails": payload.get("interviewer_emails", ""),
        "meeting_link": payload.get("meeting_link", ""),
        "prep_notes": payload.get("prep_notes", ""),
        "questions_asked": payload.get("questions_asked", ""),
        "feedback": payload.get("feedback", ""),
        "outcome": payload.get("outcome", ""),
        "follow_up_sent": 1 if payload.get("follow_up_sent") else 0,
    }


def sync_application_interview_stage(conn, app_id):
    rows = conn.execute("SELECT stage_name FROM interviews WHERE application_id=?", (app_id,)).fetchall()
    rank = 0
    for row in rows:
        rank = max(rank, interview_stage_rank(row["stage_name"]))
    conn.execute(
        "UPDATE applications SET interview_stage=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (interview_stage_from_rank(rank), app_id),
    )


def classify_rejection_reason(text):
    raw = (text or "").strip()
    lower = raw.lower()
    if not raw:
        return "Not recorded"
    if raw in REJECTION_REASONS:
        return raw
    if any(term in lower for term in ["security clearance", "clearance", "eligibility", "eligible"]):
        return "Security clearance / eligibility"
    if any(term in lower for term in ["location", "hybrid", "onsite", "remote", "relocat", "travel"]):
        return "Location / working pattern"
    if any(term in lower for term in ["salary", "rate", "compensation", "budget"]):
        return "Salary / level mismatch"
    if any(term in lower for term in ["role closed", "position closed", "hiring paused", "filled", "cancelled", "canceled"]):
        return "Role closed / hiring paused"
    if any(term in lower for term in ["experience", "seniority", "senior", "junior"]):
        return "Insufficient experience"
    if any(term in lower for term in ["skill", "alignment", "closely", "requirements", "matched", "candidates", "candidate"]):
        return "Better matched candidates"
    return "Other"


def is_user_withdrawal_reason(value):
    lower = str(value or "").strip().lower()
    return lower in {"no longer interested", "withdrawn", "rejected by me", "user rejected", "user rejection"}


def looks_like_rejection_email(text):
    raw = (text or "").strip()
    lower = raw.lower()
    return len(raw) > 80 or "\n" in raw or any(term in lower for term in ["thank you", "unfortunately", "application", "candidate"])


def migrate_rejection_reasons(conn):
    rows = conn.execute("SELECT id, rejection_reason, rejection_email FROM applications").fetchall()
    for row in rows:
        current_reason = (row["rejection_reason"] or "").strip()
        current_email = (row["rejection_email"] or "").strip()
        if not current_reason:
            continue
        if current_reason in REJECTION_REASONS:
            continue
        if looks_like_rejection_email(current_reason):
            category = classify_rejection_reason(current_reason)
            email = current_email or current_reason
            conn.execute(
                "UPDATE applications SET rejection_reason=?, rejection_email=? WHERE id=?",
                (category, email, row["id"]),
            )
        else:
            conn.execute(
                "UPDATE applications SET rejection_reason=? WHERE id=?",
                (classify_rejection_reason(current_reason), row["id"]),
            )
    conn.execute("UPDATE applications SET rejection_reason='Ghosted' WHERE status='Ghosted'")
    conn.execute("UPDATE applications SET rejection_reason='' WHERE status='Withdrawn'")
    conn.execute(
        """
        UPDATE applications
        SET status='Withdrawn',
            withdrawal_reason=COALESCE(NULLIF(withdrawal_reason, ''), rejection_reason),
            rejection_reason=''
        WHERE status IN ('Rejection', 'Rejected')
          AND LOWER(COALESCE(rejection_reason, '')) IN ('no longer interested', 'withdrawn', 'rejected by me', 'user rejected', 'user rejection')
        """
    )


APPLICATION_FIELDS = [
    "company",
    "role_title",
    "date_applied",
    "status",
    "cv_route",
    "role_type",
    "interview_stage",
    "fit_score",
    "salary",
    "location",
    "work_mode",
    "travel_requirement",
    "source",
    "job_url",
    "recruiter_name",
    "contact_email",
    "contact_phone",
    "job_description",
    "cover_letter",
    "notes",
    "rejection_reason",
    "rejection_email",
    "withdrawal_reason",
    "follow_up_date",
    "next_action",
    "tags",
    "attachment_links",
    "last_contact_date",
    "outcome_date",
    "recruiter_led",
    "contract_flag",
]


def normalize_payload(payload):
    data = {field: payload.get(field, "") for field in APPLICATION_FIELDS}
    data["company"] = data["company"].strip()
    data["role_title"] = data["role_title"].strip()
    data["date_applied"] = data["date_applied"] or today_iso()
    data["status"] = normalized_status(data["status"])
    data["status"] = data["status"] if data["status"] in STATUSES else "In Progress"
    data["interview_stage"] = normalize_interview_stage(data["interview_stage"])
    data["fit_score"] = clean_fit(data["fit_score"])
    if data["source"] not in SOURCES and data["source"]:
        data["source"] = data["source"].strip()
    if not data["role_type"]:
        data["role_type"] = infer_role_type(data)
    if data["role_type"] not in ROLE_TYPES and data["role_type"]:
        data["role_type"] = data["role_type"].strip()
    if data["rejection_reason"] not in REJECTION_REASONS and data["rejection_reason"]:
        data["rejection_reason"] = classify_rejection_reason(data["rejection_reason"])
    if data["status"] == "Ghosted":
        data["rejection_reason"] = "Ghosted"
    if data["status"] in EMPLOYER_REJECTION_STATUSES and is_user_withdrawal_reason(data["rejection_reason"]):
        data["status"] = "Withdrawn"
        data["withdrawal_reason"] = data["withdrawal_reason"] or data["rejection_reason"]
        data["rejection_reason"] = ""
    if data["status"] in WITHDRAWN_STATUSES:
        data["rejection_reason"] = ""
    if data["status"] not in WITHDRAWN_STATUSES:
        data["withdrawal_reason"] = ""
    data["recruiter_led"] = 1 if str(data["recruiter_led"]).lower() in {"1", "true", "yes", "on"} else 0
    data["contract_flag"] = 1 if str(data["contract_flag"]).lower() in {"1", "true", "yes", "on"} else 0
    if data["status"] in CLOSED_STATUSES and not data["outcome_date"]:
        data["outcome_date"] = data["last_contact_date"] or today_iso()
    if data["status"] not in CLOSED_STATUSES:
        data["outcome_date"] = ""
    return data


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
        ensure_logged_interview_stage(conn, app_id, data["interview_stage"], data["last_contact_date"] or data["date_applied"])
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
        ensure_logged_interview_stage(conn, app_id, data["interview_stage"], data["last_contact_date"] or data["date_applied"])


def list_applications(filters=None):
    filters = filters or {}
    sql = "SELECT * FROM applications"
    clauses = []
    params = []
    query = filters.get("q", "").strip()
    if query:
        clauses.append("(company LIKE ? OR role_title LIKE ? OR notes LIKE ? OR tags LIKE ?)")
        params.extend([f"%{query}%"] * 4)
    status_filter = filters.get("status")
    if filters.get("cv_route"):
        clauses.append("cv_route=?")
        params.append(filters["cv_route"])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY date_applied DESC, id DESC"
    with db() as conn:
        rows = [row_to_dict(row) for row in conn.execute(sql, params).fetchall()]
    attach_interview_history(rows)
    if status_filter:
        rows = [row for row in rows if row["effective_status"] == status_filter]
    if filters.get("active") == "1":
        rows = [row for row in rows if row["is_active"]]
    return rows


def get_application(app_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            return None
        interviews = [dict(item) for item in conn.execute("SELECT * FROM interviews WHERE application_id=? ORDER BY scheduled_at ASC, id ASC", (app_id,))]
        timeline = [dict(item) for item in conn.execute("SELECT * FROM timeline_events WHERE application_id=? ORDER BY event_date ASC, id ASC", (app_id,))]
        followups = [dict(item) for item in conn.execute("SELECT * FROM followups WHERE application_id=? ORDER BY due_date ASC, id ASC", (app_id,))]
        attachments = [dict(item) for item in conn.execute("SELECT * FROM attachments WHERE application_id=? ORDER BY id ASC", (app_id,))]
    data = row_to_dict(row)
    data["interviews"] = interviews
    attach_interview_history([data])
    latest_interview = None
    for item in interviews:
        latest_interview = latest_date(latest_interview.isoformat() if latest_interview else "", item.get("scheduled_at"))
    data["latest_interview_date"] = latest_interview.isoformat() if latest_interview else ""
    data["timeline"] = timeline
    data["followups"] = followups
    data["attachments"] = attachments
    return data


def options_data():
    with db() as conn:
        current_sources = [row["source"] for row in conn.execute("SELECT DISTINCT source FROM applications WHERE COALESCE(source, '') <> '' ORDER BY source")]
        current_role_types = [row["role_type"] for row in conn.execute("SELECT DISTINCT role_type FROM applications WHERE COALESCE(role_type, '') <> '' ORDER BY role_type")]
    return {
        "statuses": STATUSES,
        "interview_stages": INTERVIEW_STAGE_OPTIONS,
        "cv_routes": CV_ROUTES,
        "role_types": sorted(set(ROLE_TYPES) | set(current_role_types)),
        "sources": sorted(set(SOURCES) | set(current_sources)),
        "work_modes": WORK_MODES,
        "travel_requirements": TRAVEL_REQUIREMENTS,
        "rejection_reasons": REJECTION_REASONS,
    }


def performance_rows(apps, groups, field):
    rows = []
    for group in groups:
        group_apps = [app for app in apps if (app.get(field) or "Uncategorised") == group]
        count = len(group_apps)
        if not count:
            continue
        interviews = sum(1 for app in group_apps if has_interview_data(app))
        rejects = sum(1 for app in group_apps if app["effective_status"] in EMPLOYER_REJECTION_STATUSES)
        ghosted = sum(1 for app in group_apps if app["effective_status"] == "Ghosted")
        active = sum(1 for app in group_apps if app["is_active"])
        avg_fit = round(sum((app["fit_score"] or 0) for app in group_apps) / count, 2)
        confidence = "Higher confidence" if count >= 50 else "Medium confidence" if count >= 20 else "Low confidence"
        rows.append({
            "label": group,
            "applications": count,
            "avg_fit": avg_fit,
            "interviews": interviews,
            "rejections": rejects,
            "ghosted": ghosted,
            "active": active,
            "interview_rate": round(interviews / count * 100, 1),
            "rejection_rate": round(rejects / count * 100, 1),
            "ghosting_rate": round(ghosted / count * 100, 1),
            "traction": round(interviews / count * 100, 1),
            "confidence": confidence,
        })
    rows.sort(key=lambda row: (row["traction"], row["applications"]), reverse=True)
    return rows


def outcome_rates(rows):
    total = len(rows)
    if not total:
        return None
    return {
        "interview": sum(1 for app in rows if has_interview_data(app)) / total * 100,
        "rejection": sum(1 for app in rows if app["effective_status"] in EMPLOYER_REJECTION_STATUSES) / total * 100,
        "offer": sum(1 for app in rows if app["effective_status"] == "Offer") / total * 100,
        "ghosted": sum(1 for app in rows if app["effective_status"] == "Ghosted") / total * 100,
    }


def blended_segment_rates(apps, field, value, baseline):
    closed = [app for app in apps if not app["is_active"]]
    segment = [app for app in closed if app.get(field) == value]
    rates = outcome_rates(segment)
    if len(segment) >= 10 and rates:
        return rates
    if len(segment) >= 5 and rates:
        return {key: baseline[key] * 0.8 + rates[key] * 0.2 for key in baseline}
    return baseline


def engagement_level(row):
    status = row["effective_status"]
    if status == "Interview":
        return "Screening"
    has_contact = any([
        row.get("recruiter_name"),
        row.get("contact_email"),
        row.get("contact_phone"),
        row.get("recruiter_led"),
        row.get("last_contact_date") and row.get("last_contact_date") != row.get("date_applied"),
    ])
    if has_contact:
        return "Engaged"
    return "Application-only"


def latest_date(*values):
    parsed = [parse_date(value) for value in values]
    parsed = [value for value in parsed if value]
    return max(parsed) if parsed else None


def days_since_meaningful_activity(row):
    activity = latest_date(
        row.get("last_contact_date"),
        row.get("latest_interview_date"),
        row.get("latest_followup_date"),
        row.get("date_applied"),
    )
    return days_between(activity.isoformat() if activity else row.get("date_applied"))


def has_recruiter_activity(row):
    return engagement_level(row) != "Application-only" or bool(row.get("latest_followup_date"))


def final_interview_count(apps):
    return sum(1 for app in apps if has_interview_reached(app, "Stage 3"))


def funnel_rows(apps):
    total = len(apps)
    stages = [
        ("Recruiter contact / screening", sum(1 for app in apps if has_recruiter_activity(app))),
        ("Interviews", sum(1 for app in apps if has_interview_data(app))),
        ("Stage 3 interviews", final_interview_count(apps)),
        ("Offers", sum(1 for app in apps if app["effective_status"] == "Offer")),
        ("Rejections", sum(1 for app in apps if app["effective_status"] in EMPLOYER_REJECTION_STATUSES)),
        ("Ghosted", sum(1 for app in apps if app["effective_status"] == "Ghosted")),
        ("Withdrawn", sum(1 for app in apps if app["effective_status"] in WITHDRAWN_STATUSES)),
    ]
    rows = []
    previous = None
    for label, count in stages:
        rows.append({
            "label": label,
            "count": count,
            "percent_total": round(count / total * 100, 1) if total else 0,
            "conversion": round(count / previous * 100, 1) if previous else None,
        })
        previous = count if count else None
    return rows


def conversion_metrics(apps):
    total = len(apps)
    contacted = sum(1 for app in apps if has_recruiter_activity(app) or has_interview_data(app))
    interviews = sum(1 for app in apps if has_interview_data(app))
    offers = sum(1 for app in apps if app["effective_status"] == "Offer")
    return {
        "meaningful_contact_rate": round(contacted / total * 100, 1) if total else 0,
        "applications_to_contact_rate": round(contacted / total * 100, 1) if total else 0,
        "contact_to_interview_rate": round(interviews / contacted * 100, 1) if contacted else 0,
        "interview_to_offer_rate": round(offers / interviews * 100, 1) if interviews else 0,
        "contacted": contacted,
        "interviews": interviews,
        "offers": offers,
    }


def pipeline_score(apps):
    active = [app for app in apps if app["is_active"]]
    if not active:
        return {"score": 0, "label": "Weak", "explanation": "No active applications are currently in motion."}
    points = 0
    drivers = {"interviews": 0, "contact": 0, "fresh": 0, "older": 0}
    for app in active:
        status = app["effective_status"]
        if has_interview_data(app):
            points += 10
            drivers["interviews"] += 1
        elif has_recruiter_activity(app):
            points += 5
            drivers["contact"] += 1
        elif app["days_active"] < 14:
            points += 2
            drivers["fresh"] += 1
        elif app["days_active"] <= 20:
            points += 1
            drivers["older"] += 1
    score = round(points / (len(active) * 10) * 100, 1)
    active_interviews = drivers["interviews"]
    if score >= 70:
        label = "Exceptional"
    elif score >= 40:
        label = "Strong"
    elif score >= 20 or active_interviews > 0:
        label = "Stable"
    else:
        label = "Weak"
    parts = []
    if drivers["interviews"]:
        parts.append(f"{drivers['interviews']} interview-led role(s)")
    if drivers["contact"]:
        parts.append(f"{drivers['contact']} role(s) with recruiter activity")
    if drivers["fresh"]:
        parts.append(f"{drivers['fresh']} fresh in-progress role(s)")
    explanation = ", ".join(parts) if parts else "Mostly older in-progress roles with little recent activity."
    return {"score": score, "label": label, "explanation": explanation}


def outcome_timing_rows(apps):
    rejected = [app for app in apps if app["effective_status"] in EMPLOYER_REJECTION_STATUSES]
    rows = [
        ("Rejected within 0-2 days", sum(1 for app in rejected if app["days_active"] <= 2)),
        ("Rejected within 3-7 days", sum(1 for app in rejected if 3 <= app["days_active"] <= 7)),
        ("Rejected within 8-21 days", sum(1 for app in rejected if 8 <= app["days_active"] <= 21)),
        ("Rejected after 21 days", sum(1 for app in rejected if app["days_active"] > 21)),
        ("Ghosted (21+ days with no response)", sum(1 for app in apps if app["effective_status"] == "Ghosted")),
        ("Interviews", sum(1 for app in apps if has_interview_data(app))),
    ]
    return [{"label": label, "value": value} for label, value in rows]


def rejection_reason_category(app):
    reason = (app.get("rejection_reason") or "").strip()
    lower = reason.lower()
    if not reason or reason == "Not recorded":
        return "Immediate Rejection (0-2 days)" if app["days_active"] <= 2 else "Unknown"
    if "immediate" in lower:
        return "Immediate Rejection (0-2 days)"
    if "no response" in lower or "ghosted" in lower or "no reply" in lower:
        return "No response / ghosted"
    if "matched" in lower or "candidate" in lower:
        return "Better matched candidates"
    if "skill" in lower or "experience" in lower:
        return "Skills mismatch"
    if any(term in lower for term in ["salary", "location", "working", "hybrid", "remote", "onsite"]):
        return "Salary / location / working pattern"
    if "closed" in lower or "paused" in lower:
        return "Role closed / hiring paused"
    return "Unknown"


def rejection_reason_rows(apps):
    labels = [
        "Immediate Rejection (0-2 days)",
        "Better matched candidates",
        "No response / ghosted",
        "Skills mismatch",
        "Salary / location / working pattern",
        "Role closed / hiring paused",
        "Unknown",
    ]
    counts = {label: 0 for label in labels}
    for app in apps:
        if app["effective_status"] in EMPLOYER_REJECTION_STATUSES:
            counts[rejection_reason_category(app)] += 1
    known = [label for label in labels if label != "Unknown"]
    rows = [{"label": label, "value": counts[label]} for label in known if counts[label]]
    rows.sort(key=lambda row: row["value"], reverse=True)
    if counts["Unknown"]:
        rows.append({"label": "Unknown", "value": counts["Unknown"]})
    return rows


def fit_band(value):
    score = float(value or 0)
    if score < 2:
        return "0-2"
    if score < 3:
        return "2-3"
    if score < 4:
        return "3-4"
    if score < 4.5:
        return "4-4.5"
    return "4.5-5"


def role_quality_rows(apps):
    bands = ["0-2", "2-3", "3-4", "4-4.5", "4.5-5"]
    rows = []
    for band in bands:
        band_apps = [app for app in apps if fit_band(app.get("fit_score")) == band]
        count = len(band_apps)
        active = sum(1 for app in band_apps if app["is_active"])
        interviews = sum(1 for app in band_apps if has_interview_data(app))
        rejections = sum(1 for app in band_apps if app["effective_status"] in EMPLOYER_REJECTION_STATUSES)
        ghosted = sum(1 for app in band_apps if app["effective_status"] == "Ghosted")
        rows.append({
            "label": band,
            "applications": count,
            "active": active,
            "interviews": interviews,
            "rejections": rejections,
            "ghosted": ghosted,
            "interview_rate": round(interviews / count * 100, 1) if count else 0,
            "ghosting_rate": round(ghosted / count * 100, 1) if count else 0,
        })
    high = next((row for row in rows if row["label"] == "4.5-5"), {"interview_rate": 0})
    mid = next((row for row in rows if row["label"] == "3-4"), {"interview_rate": 0})
    note = "Higher-fit roles are producing stronger traction." if high["interview_rate"] > mid["interview_rate"] else "Higher-fit roles are not yet clearly outperforming the rest."
    return rows, note


def offer_forecast(apps):
    active = [app for app in apps if app["is_active"]]
    active_interviews = sum(1 for app in active if has_interview_data(app))
    recruiter_contact = sum(1 for app in active if has_recruiter_activity(app) and not has_interview_data(app))
    high_fit = sum(1 for app in active if (app.get("fit_score") or 0) >= 4.5)
    medium_fit = sum(1 for app in active if 4.0 <= (app.get("fit_score") or 0) < 4.5)
    interview_total = sum(1 for app in apps if has_interview_data(app))
    offers = sum(1 for app in apps if app["effective_status"] == "Offer")
    historical_rate = offers / interview_total if interview_total else None
    if active_interviews <= 0:
        base_min, base_max = 0, 10
    elif active_interviews == 1:
        base_min, base_max = 10, 20
    elif active_interviews == 2:
        base_min, base_max = 20, 40
    else:
        base_min, base_max = 35, 60
    support = min(1, recruiter_contact * 0.04 + high_fit * 0.025 + medium_fit * 0.012)
    chance_30 = round(base_min + (base_max - base_min) * support, 1)
    chance_60 = round(min(75, chance_30 + 10 + active_interviews * 5 + min(10, recruiter_contact * 0.8)), 1)
    chance_by_target = offer_chances_by_target(chance_30, chance_60)
    confidence = "High" if active_interviews >= 3 and offers else "Medium" if active_interviews >= 1 else "Low"
    note = (
        f"Uses historical interview-to-offer rate of {round(historical_rate * 100, 1)}% plus current pipeline composition."
        if historical_rate is not None and offers
        else "No historical offer data available. Forecast is based on current pipeline composition only."
    )
    top_roles = []
    for app in active:
        forecast = forecast_for(app, apps)
        base_offer_chance = role_offer_likelihood(app)
        top_roles.append({
            "id": app["id"],
            "company": app["company"],
            "role_title": app["role_title"],
            "offer_chance": base_offer_chance,
            "offer_chances": role_offer_chances_by_target(base_offer_chance),
            "engagement_level": forecast["engagement_level"],
            "fit_score": app.get("fit_score") or 0,
        })
    top_roles.sort(key=lambda row: (row["offer_chance"], row["fit_score"], row["company"]), reverse=True)
    return {
        "chance_30": chance_30,
        "chance_60": chance_60,
        "chance_by_target": chance_by_target,
        "confidence": confidence,
        "note": note,
        "active_interviews": active_interviews,
        "recruiter_contact_active": recruiter_contact,
        "high_fit_active": high_fit,
        "medium_fit_active": medium_fit,
        "historical_interview_to_offer_rate": round(historical_rate * 100, 1) if historical_rate is not None else None,
        "top_roles": top_roles[:3],
    }


def offer_chances_by_target(chance_30, chance_60):
    chance_30 = number_safe(chance_30)
    chance_60 = number_safe(chance_60)
    gain = max(0, chance_60 - chance_30)
    return {
        "30": round(chance_30, 1),
        "60": round(chance_60, 1),
        "90": round(min(85, chance_60 + gain * 0.65), 1),
        "120": round(min(90, chance_60 + gain * 1.05), 1),
    }


def role_offer_chances_by_target(base_chance):
    base_chance = number_safe(base_chance)
    return {
        "30": round(max(1, min(70, base_chance * 0.78)), 1),
        "60": round(max(1, min(70, base_chance)), 1),
        "90": round(max(1, min(80, base_chance + (80 - base_chance) * 0.18)), 1),
        "120": round(max(1, min(85, base_chance + (85 - base_chance) * 0.30)), 1),
    }


def number_safe(value):
    return float(value or 0)


def role_offer_likelihood(app):
    rank = interview_stage_rank(get_interview_stage(app))
    level = engagement_level(app)
    if rank >= interview_stage_rank("Stage 3"):
        score = 62
    elif rank >= interview_stage_rank("Stage 2"):
        score = 54
    elif rank >= interview_stage_rank("Stage 1"):
        score = 45
    elif rank >= interview_stage_rank("Screening") or level == "Screening":
        score = 32
    elif level == "Engaged":
        score = 16
    else:
        score = 6

    fit = app.get("fit_score") or 3
    score += (fit - 3) * 5

    days = app.get("days_since_last_contact")
    if days is None:
        days = app.get("days_active", 0)
    if days <= 3:
        score += 5
    elif days <= 7:
        score += 2
    elif days >= 21:
        score -= 10
    elif days >= 14:
        score -= 5

    if app.get("effective_status") == "Interview":
        score += 4
    if app.get("recruiter_led"):
        score += 2

    return round(max(1, min(70, score)), 1)


def weekly_application_target(apps, offer, interview_total):
    if not apps:
        return {"target": 0, "label": "No target yet", "note": "Add applications to calculate a search pace target."}
    app_to_interview = interview_total / len(apps) if apps else 0
    app_to_interview = max(app_to_interview, 0.03)
    chance_60 = offer.get("chance_60") or 0
    shortfall = max(0, 50 - chance_60)
    needed_interviews = max(1, int((shortfall / 15) + 0.999))
    target = max(1, int((needed_interviews / app_to_interview / 8) + 0.999))
    return {
        "target": target,
        "label": f"Offer pace {target}/wk",
        "note": (
            f"Based on {round(app_to_interview * 100, 1)}% application-to-interview conversion, "
            f"{chance_60}% 60-day offer forecast, and {needed_interviews} interview opportunity target over 8 weeks."
        ),
    }


def forecast_for(row, apps):
    fit = row["fit_score"] or 3
    days = row["days_since_last_contact"]
    status = row["effective_status"]
    level = engagement_level(row)
    baselines = {
        "Application-only": {"interview": 5, "rejection": 55, "offer": 0.1, "ghosted": 40},
        "Engaged": {"interview": 35, "rejection": 45, "offer": 2, "ghosted": 18},
        "Screening": {"interview": 55, "rejection": 35, "offer": 3, "ghosted": 7},
        "Interview": {"interview": 25, "rejection": 60, "offer": 8, "ghosted": 7},
    }
    baseline = dict(baselines[level])

    route_rates = blended_segment_rates(apps, "cv_route", row.get("cv_route"), baseline)
    source_rates = blended_segment_rates(apps, "source", row.get("source"), baseline)
    role_rates = blended_segment_rates(apps, "role_type", row.get("role_type"), baseline)
    weights = {
        key: baseline[key] * 0.7 + ((route_rates[key] + source_rates[key] + role_rates[key]) / 3) * 0.3
        for key in baseline
    }

    if fit >= 4.5:
        weights["interview"] *= 1.20
        weights["rejection"] *= 0.95
        weights["offer"] *= 1.10
    elif fit >= 3.5:
        weights["interview"] *= 1.10
    elif fit < 2.5:
        weights["interview"] *= 0.75
        weights["rejection"] *= 1.15
    if fit < 3:
        weights["offer"] *= 0.75

    if level == "Application-only":
        if days >= 22:
            weights["ghosted"] *= 1.60
            weights["interview"] *= 0.60
        elif days >= 15:
            weights["ghosted"] *= 1.35
            weights["interview"] *= 0.75
        elif days >= 8:
            weights["ghosted"] *= 1.15
            weights["interview"] *= 0.90
    else:
        if days >= 22:
            weights["ghosted"] *= 1.35
            weights["interview"] *= 0.80
        elif days >= 15:
            weights["ghosted"] *= 1.20
            weights["interview"] *= 0.90
        elif days >= 8:
            weights["ghosted"] *= 1.10

    offer_caps = {
        "Application-only": 0.25,
        "Engaged": 3,
        "Screening": 5,
        "Interview": 10,
    }
    offer_cap = offer_caps[level]
    weights["offer"] = min(weights["offer"], offer_cap)

    for key in weights:
        weights[key] = max(weights[key], 0)
    total = sum(weights.values()) or 1
    normalized = {key: weights[key] / total for key in weights}
    normalized["engagement_level"] = level
    return normalized


def latest_role_summary(apps, *date_fields):
    if not apps:
        return None

    def sort_key(app):
        parsed_dates = [parse_date(app.get(field)) for field in date_fields]
        latest = max((item for item in parsed_dates if item), default=date.min)
        return (latest, app.get("id") or 0)

    latest = max(apps, key=sort_key)
    return {
        "company": latest.get("company") or "",
        "role_title": latest.get("role_title") or "",
        "fit_score": latest.get("fit_score"),
    }


def interview_timing_counts(interview_rows):
    today = date.today()
    counts = {"completed": 0, "future": 0}
    for row in interview_rows:
        scheduled = parse_date(row["scheduled_at"])
        if scheduled and scheduled > today:
            counts["future"] += 1
        else:
            counts["completed"] += 1
    return counts


def dashboard_data():
    apps = list_applications()
    with db() as conn:
        interview_rows = conn.execute("SELECT scheduled_at FROM interviews").fetchall()
        followup_rows = conn.execute("SELECT application_id, due_date, completed FROM followups").fetchall()
    followup_dates = {}
    followup_sent = {}
    for row in followup_rows:
        app_id = row["application_id"]
        current = latest_date(followup_dates.get(app_id), row["due_date"])
        followup_dates[app_id] = current.isoformat() if current else followup_dates.get(app_id, "")
        followup_sent[app_id] = bool(followup_sent.get(app_id)) or bool(row["completed"])
    for app in apps:
        app["latest_followup_date"] = followup_dates.get(app["id"], "")
        app["followup_sent"] = followup_sent.get(app["id"], False)
        app["days_since_last_activity"] = days_since_meaningful_activity(app)

    active = [app for app in apps if app["is_active"]]
    total = len(apps)
    interview_breakdown = interview_breakdown_counts(apps)
    interviews = get_interviewed_application_count(apps)
    interview_events = get_interview_event_count(apps)
    rejections = sum(1 for app in apps if app["effective_status"] in EMPLOYER_REJECTION_STATUSES)
    post_interview = sum(1 for app in apps if app["effective_status"] == "Rejection Post Interview")
    ghosted = sum(1 for app in apps if app["effective_status"] == "Ghosted")
    offers = sum(1 for app in apps if app["effective_status"] == "Offer")
    withdrawn = sum(1 for app in apps if app["effective_status"] in WITHDRAWN_STATUSES)
    closed_outcomes = sum(1 for app in apps if app["effective_status"] in ALL_CLOSED_OUTCOME_STATUSES)
    this_week = sum(1 for app in apps if days_between(app["date_applied"]) <= date.today().weekday())
    avg_active = round(sum(app["days_active"] for app in active) / len(active), 1) if active else 0
    median_active = median([app["days_active"] for app in active])
    avg_last_contact = round(sum(app["days_since_last_contact"] for app in active) / len(active), 1) if active else 0
    rejected_apps = [app for app in apps if app["effective_status"] in EMPLOYER_REJECTION_STATUSES]
    avg_rejection_time = round(sum(app["days_active"] for app in rejected_apps) / len(rejected_apps), 1) if rejected_apps else 0
    closed_total_apps = [app for app in apps if app["effective_status"] in ALL_CLOSED_OUTCOME_STATUSES]
    avg_days_total = round(sum(app["days_active"] for app in closed_total_apps) / len(closed_total_apps), 1) if closed_total_apps else 0
    response_apps = [app for app in apps if app["last_contact_date"] and app["last_contact_date"] != app["date_applied"]]
    avg_response_time = round(sum(days_between(app["date_applied"], app["last_contact_date"]) for app in response_apps) / len(response_apps), 1) if response_apps else 0

    status_breakdown = {status: 0 for status in STATUSES}
    for app in apps:
        status_breakdown[app["effective_status"]] = status_breakdown.get(app["effective_status"], 0) + 1

    score = pipeline_score(apps)
    conversions = conversion_metrics(apps)
    interview_timing = interview_timing_counts(interview_rows)

    ageing = {"0-7 days": 0, "8-14 days": 0, "15-20 days": 0, "21+ days": 0}
    for app in active:
        if app["effective_status"] in {"In Progress", "Interview"}:
            ageing[ageing_bucket(app["days_active"])] += 1

    weekly = {}
    weekly_fields = ("applications", "rejections", "ghosted", "interviews")

    def week_label(value):
        parsed = parse_date(value)
        if not parsed:
            return None
        monday = parsed.fromordinal(parsed.toordinal() - parsed.weekday())
        return monday.isoformat()

    def weekly_bucket(label):
        if label not in weekly:
            weekly[label] = {field: 0 for field in weekly_fields}
        return weekly[label]

    for app in apps:
        applied_week = week_label(app["date_applied"])
        if applied_week:
            weekly_bucket(applied_week)["applications"] += 1

        status = app["effective_status"]
        event_date = app["outcome_date"] if app["status"] in CLOSED_STATUSES else app["last_contact_date"]
        if app["status"] == "In Progress" and status == "Ghosted":
            event_date = app["effective_ghosted_date"]
        event_week = week_label(event_date)
        if status in ALL_CLOSED_OUTCOME_STATUSES and not event_week:
            event_week = week_label(app["date_applied"])
        if not event_week:
            continue
        if status in EMPLOYER_REJECTION_STATUSES:
            weekly_bucket(event_week)["rejections"] += 1
        if status == "Ghosted":
            weekly_bucket(event_week)["ghosted"] += 1

    for app in apps:
        if not has_interview_data(app):
            continue
        interview_week = week_label(app.get("latest_interview_date") or app.get("last_contact_date") or app.get("date_applied"))
        if interview_week:
            weekly_bucket(interview_week)["interviews"] += 1

    route_rows = performance_rows(apps, CV_ROUTES, "cv_route")
    best_route = max(route_rows, key=lambda row: row["traction"], default=None)
    role_type_groups = sorted({app["role_type"] or "Uncategorised" for app in apps} | set(ROLE_TYPES))
    source_groups = sorted({app["source"] or "Uncategorised" for app in apps} | set(SOURCES))
    role_type_rows = performance_rows(apps, role_type_groups, "role_type")
    role_type_rows.sort(key=lambda row: (row["label"] == "Uncategorised", -row["applications"], row["label"]))
    source_rows = performance_rows(apps, source_groups, "source")
    quality_rows, quality_note = role_quality_rows(apps)
    offer = offer_forecast(apps)
    weekly_target = weekly_application_target(apps, offer, interviews)
    weekly_rows = [
        {"week": key, **weekly[key], "target": weekly_target["target"], "target_label": weekly_target["label"], "target_note": weekly_target["note"]}
        for key in sorted(weekly)[-8:]
    ]

    followups = []
    for app in active:
        if app["effective_status"] in ALL_CLOSED_OUTCOME_STATUSES:
            continue
        fit = app["fit_score"] or 0
        is_interview = has_interview_data(app)
        activity_days = app["days_since_last_activity"]
        priority = (1000 if is_interview else 0) + fit * 100 + min(activity_days, 30) * 4 + min(app["days_active"], 30)
        if is_interview and app.get("followup_sent"):
            action = "Wait for feedback"
        elif is_interview:
            action = "Prepare for interview"
        elif fit >= 4.5 and activity_days >= 14:
            action = "Follow up now"
        elif app["effective_status"] == "In Progress" and app["days_active"] >= 18:
            action = "Mark ghosted soon"
        elif activity_days >= 7:
            action = "Follow up now"
        elif app.get("followup_sent"):
            action = "No action"
        else:
            action = "Monitor"
        followups.append({
            "id": app["id"],
            "company": app["company"],
            "role_title": app["role_title"],
            "days_active": app["days_active"],
            "days_since_last_activity": activity_days,
            "status": app["effective_status"],
            "fit_score": app["fit_score"],
            "suggested_action": action,
            "priority_score": round(priority, 1),
        })
    followups.sort(key=lambda item: item["priority_score"], reverse=True)

    return {
        "kpis": {
            "total": total,
            "active": len(active),
            "rejections": rejections,
            "ghosted": ghosted,
            "interviews": interviews,
            "interview_events": interview_events,
            "completed_interviews": interview_timing["completed"],
            "future_interviews": interview_timing["future"],
            "interview_breakdown": interview_breakdown,
            "post_interview_rejections": post_interview,
            "latest_active_application": latest_role_summary(active, "date_applied"),
            "latest_rejection": latest_role_summary(rejected_apps, "outcome_date", "last_contact_date", "date_applied"),
            "latest_ghosted": latest_role_summary(
                [app for app in apps if app["effective_status"] == "Ghosted"],
                "effective_ghosted_date",
                "last_contact_date",
                "date_applied",
            ),
            "offers": offers,
            "withdrawn": withdrawn,
            "closed_outcomes": closed_outcomes,
            "applications_this_week": this_week,
            "average_days_active": avg_active,
            "average_days_total": avg_days_total,
            "median_active_days": median_active,
            "average_days_since_last_contact": avg_last_contact,
            "average_response_time": avg_response_time,
            "average_rejection_time": avg_rejection_time,
            "interview_conversion_rate": round(interviews / total * 100, 1) if total else 0,
            "meaningful_contact_rate": conversions["meaningful_contact_rate"],
            "weighted_pipeline_score": score["score"],
            "pipeline_health_label": score["label"],
        },
        "pipeline_score": score,
        "interview_funnel": funnel_rows(apps),
        "conversion_metrics": conversions,
        "outcome_timing": outcome_timing_rows(apps),
        "weekly": weekly_rows,
        "weekly_target": weekly_target,
        "status_breakdown": [{"label": key, "value": value} for key, value in status_breakdown.items()],
        "ageing": [{"label": key, "value": value} for key, value in ageing.items()],
        "cv_routes": route_rows,
        "best_route": best_route,
        "role_types": role_type_rows,
        "sources": source_rows[:10],
        "rejection_reasons": rejection_reason_rows(apps),
        "role_quality": quality_rows,
        "role_quality_note": quality_note,
        "offer_forecast": offer,
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
            "status": raw.get("Stage") or raw.get("Status") or raw.get("status") or "In Progress",
            "cv_route": raw.get("Best CV Route") or raw.get("CV Route") or raw.get("cv_route") or "",
            "role_type": raw.get("Role Type") or raw.get("role_type") or "",
            "interview_stage": raw.get("Interview Stage") or raw.get("Interview Stage Reached") or raw.get("interview_stage") or "",
            "fit_score": raw.get("Market Fit %") or raw.get("Fit Score") or raw.get("fit_score") or "",
            "salary": raw.get("Salary") or raw.get("salary") or "",
            "location": raw.get("Location/Remote") or raw.get("Location") or raw.get("location") or "",
            "source": raw.get("Source") or raw.get("source") or "",
            "job_url": raw.get("Application URL") or raw.get("Job URL") or raw.get("job_url") or "",
            "notes": raw.get("Comments") or raw.get("Notes") or raw.get("notes") or "",
            "rejection_reason": raw.get("Rejection Reason") or raw.get("rejection_reason") or "",
            "rejection_email": raw.get("Rejection Email") or raw.get("rejection_email") or "",
            "withdrawal_reason": raw.get("Withdrawal Reason") or raw.get("Rejected By Me Reason") or raw.get("withdrawal_reason") or "",
            "follow_up_date": raw.get("Follow-up Date") or raw.get("follow_up_date") or "",
            "next_action": raw.get("Next Action") or raw.get("next_action") or "",
            "last_contact_date": raw.get("Last Update") or raw.get("last_contact_date") or "",
        }
        if payload["company"] and payload["role_title"]:
            create_application(payload)
            count += 1
    return count


def applications_csv_text(apps=None):
    apps = list_applications() if apps is None else apps
    output = io.StringIO()
    fields = ["id"] + APPLICATION_FIELDS + ["effective_status", "effective_ghosted_date", "days_active", "ageing_bucket"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for app in apps:
        row = {field: app.get(field, "") for field in fields}
        row["interview_stage"] = get_interview_stage(app)
        writer.writerow(row)
    return output.getvalue()


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
        if parsed.path == "/api/options":
            return self.send_json(options_data())
        if parsed.path == "/api/dashboard":
            return self.send_json(dashboard_data())
        if parsed.path == "/api/applications":
            return self.send_json(list_applications({key: values[0] for key, values in parse_qs(parsed.query).items()}))
        if parsed.path == "/api/attachments/preview":
            requested = parse_qs(parsed.query).get("path", [""])[0]
            path = local_file_path(requested)
            if not path:
                return self.send_json({"error": "Attachment file was not found."}, HTTPStatus.NOT_FOUND)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return self.serve_file(path, content_type)
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
            text = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
            count = import_csv_text(text)
            return self.send_json({"imported": count})
        if parsed.path == "/api/attachments/open":
            payload = self.read_json()
            path = local_file_path(payload.get("path"))
            if not path:
                return self.send_json({"error": "Attachment file was not found."}, HTTPStatus.NOT_FOUND)
            try:
                subprocess.Popen(["open", str(path)])
            except OSError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return self.send_json({"ok": True})
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/interviews"):
            app_id = clean_int(parsed.path.split("/")[-2])
            payload = interview_payload(self.read_json())
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
                        payload["stage_name"],
                        payload.get("scheduled_at", ""),
                        payload.get("interviewer_names", ""),
                        payload.get("interviewer_emails", ""),
                        payload.get("meeting_link", ""),
                        payload.get("prep_notes", ""),
                        payload.get("questions_asked", ""),
                        payload.get("feedback", ""),
                        payload.get("outcome", ""),
                        payload["follow_up_sent"],
                    ),
                )
                conn.execute(
                    "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
                    (app_id, payload.get("scheduled_at", today_iso())[:10] or today_iso(), "Interview", payload["stage_name"]),
                )
                current = conn.execute("SELECT status, interview_stage FROM applications WHERE id=?", (app_id,)).fetchone()
                if current:
                    current_stage = normalize_interview_stage(current["interview_stage"])
                    reached_stage = payload["stage_name"]
                    if interview_stage_rank(current_stage) > interview_stage_rank(reached_stage):
                        reached_stage = current_stage
                    new_status = "Interview" if current["status"] == "In Progress" else current["status"]
                    conn.execute(
                        "UPDATE applications SET status=?, interview_stage=?, last_contact_date=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (new_status, reached_stage, payload.get("scheduled_at", today_iso())[:10] or today_iso(), app_id),
                    )
            return self.send_json({"id": cur.lastrowid}, HTTPStatus.CREATED)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/followups"):
            app_id = clean_int(parsed.path.split("/")[-2])
            payload = self.read_json()
            due_date = payload.get("due_date") or today_iso()
            action = payload.get("action") or "Follow up"
            notes = payload.get("notes", "")
            with db() as conn:
                cur = conn.execute(
                    "INSERT INTO followups (application_id, due_date, action, notes, completed) VALUES (?, ?, ?, ?, ?)",
                    (app_id, due_date, action, notes, 1 if payload.get("completed") else 0),
                )
                conn.execute(
                    "UPDATE applications SET follow_up_date=?, next_action=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (due_date, action, app_id),
                )
                conn.execute(
                    "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
                    (app_id, due_date, "Follow-up", f"{action} {notes}".strip()),
                )
            return self.send_json({"id": cur.lastrowid}, HTTPStatus.CREATED)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/attachments"):
            app_id = clean_int(parsed.path.split("/")[-2])
            payload = self.read_json()
            try:
                if payload.get("file_content"):
                    stored_path = save_uploaded_attachment(app_id, payload.get("file_name"), payload.get("file_content"))
                    original_path = payload.get("path") or payload.get("file_name") or ""
                else:
                    stored_path = copy_attachment_to_store(app_id, payload.get("path"))
                    original_path = payload.get("path") or ""
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            kind = payload.get("kind") or mimetypes.guess_type(stored_path.name)[0] or ""
            notes = payload.get("notes") or ""
            if original_path and clean_file_path(original_path) != str(stored_path):
                notes = "\n".join(part for part in [notes, f"Original: {clean_file_path(original_path)}"] if part)
            with db() as conn:
                cur = conn.execute(
                    "INSERT INTO attachments (application_id, label, path, kind, notes) VALUES (?, ?, ?, ?, ?)",
                    (app_id, payload.get("label") or stored_path.name, str(stored_path), kind, notes),
                )
                conn.execute("UPDATE applications SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (app_id,))
            return self.send_json({"id": cur.lastrowid}, HTTPStatus.CREATED)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/action"):
            app_id = clean_int(parsed.path.split("/")[-2])
            payload = self.read_json()
            action = payload.get("action")
            status_map = {
                "ghosted": "Ghosted",
                "rejected": "Rejection",
                "interview1": "Interview",
                "offer": "Offer",
                "withdrawn": "Withdrawn",
            }
            if action not in status_map:
                return self.send_json({"error": "Unknown action"}, HTTPStatus.BAD_REQUEST)
            with db() as conn:
                before = conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
                if not before:
                    return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                new_status = status_map[action]
                outcome_date = today_iso() if new_status in CLOSED_STATUSES else ""
                extra_sets = []
                extra_values = []
                if new_status == "Interview":
                    extra_sets.append("interview_stage=?")
                    extra_values.append("Stage 1")
                if new_status == "Withdrawn":
                    extra_sets.extend(["rejection_reason=?", "withdrawal_reason=?"])
                    extra_values.extend(["", "Withdrawn by me"])
                conn.execute(
                    """
                    UPDATE applications
                    SET status=?, last_contact_date=?, outcome_date=?{extra}, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """.format(extra=(", " + ", ".join(extra_sets)) if extra_sets else ""),
                    [new_status, today_iso(), outcome_date] + extra_values + [app_id],
                )
                conn.execute(
                    "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
                    (app_id, today_iso(), "Quick Action", f"{before['status']} -> {new_status}"),
                )
                if new_status == "Interview":
                    ensure_logged_interview_stage(conn, app_id, "Stage 1", today_iso())
            return self.send_json({"ok": True})
        return self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/applications/") and "/interviews/" in parsed.path:
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "applications" and parts[3] == "interviews":
                app_id = clean_int(parts[2])
                interview_id = clean_int(parts[4])
                payload = interview_payload(self.read_json())
                with db() as conn:
                    existing = conn.execute(
                        "SELECT id FROM interviews WHERE id=? AND application_id=?",
                        (interview_id, app_id),
                    ).fetchone()
                    if not existing:
                        return self.send_json({"error": "Interview not found."}, HTTPStatus.NOT_FOUND)
                    conn.execute(
                        """
                        UPDATE interviews
                        SET stage_name=?, scheduled_at=?, interviewer_names=?, interviewer_emails=?,
                            meeting_link=?, prep_notes=?, questions_asked=?, feedback=?, outcome=?,
                            follow_up_sent=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=? AND application_id=?
                        """,
                        (
                            payload["stage_name"],
                            payload["scheduled_at"],
                            payload["interviewer_names"],
                            payload["interviewer_emails"],
                            payload["meeting_link"],
                            payload["prep_notes"],
                            payload["questions_asked"],
                            payload["feedback"],
                            payload["outcome"],
                            payload["follow_up_sent"],
                            interview_id,
                            app_id,
                        ),
                    )
                    sync_application_interview_stage(conn, app_id)
                    conn.execute(
                        "INSERT INTO timeline_events (application_id, event_date, event_type, details) VALUES (?, ?, ?, ?)",
                        (app_id, payload["scheduled_at"][:10] or today_iso(), "Interview Update", payload["stage_name"]),
                    )
                return self.send_json({"ok": True})
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
        try:
            body = path.read_bytes()
        except PermissionError:
            return self.send_error(HTTPStatus.FORBIDDEN, "File access is blocked by macOS privacy permissions.")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def export_applications_csv(self):
        body = applications_csv_text().encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv")
        self.send_header("Content-Disposition", "attachment; filename=job_applications_export.csv")
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
