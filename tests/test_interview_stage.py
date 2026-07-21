import csv
import importlib.util
import io
from pathlib import Path
import sqlite3
import unittest


APP_PATH = Path(__file__).resolve().parents[1] / "app" / "app.py"
SPEC = importlib.util.spec_from_file_location("job_tracker_app", APP_PATH)
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class InterviewStageTests(unittest.TestCase):
    def sample_applications(self):
        return [
            {"id": 1, "interview_stages": "Screening", "interview_stage": "", "status": "Interview"},
            {"id": 2, "interview_stages": "Screening", "interview_stage": "", "status": "Withdrawn"},
            {"id": 3, "interview_stages": "Stage 1", "interview_stage": "", "status": "Interview"},
            {"id": 4, "interview_stages": "Screening | Stage 1", "interview_stage": "", "status": "Rejection Post Interview"},
            {"id": 5, "interview_stages": "Stage 1", "interview_stage": "", "status": "Offer"},
            {"id": 6, "interview_stages": "", "interview_stage": "Stage 1", "status": "Interview"},
            {"id": 7, "interview_stages": "", "interview_stage": "Stage 1", "status": "Rejection Post Interview"},
            {"id": 8, "interview_stages": "", "interview_stage": None, "status": "In Progress"},
        ]

    def test_stage_counts_use_logged_interview_history_only(self):
        counts = app.get_interview_stage_counts(self.sample_applications())

        self.assertEqual(app.get_interviewed_application_count(self.sample_applications()), 5)
        self.assertEqual(counts["screening"], 5)
        self.assertEqual(counts["stage_1"], 3)
        self.assertEqual(counts["stage_2"], 0)
        self.assertEqual(counts["stage_3"], 0)
        self.assertEqual(app.get_interview_event_count(self.sample_applications()), 8)

    def test_blank_and_status_only_interviews_are_not_counted(self):
        blank_interview = {"interview_stages": "", "interview_stage": "Stage 1", "status": "Interview"}
        post_interview_rejection_blank = {"interview_stages": "", "interview_stage": "Stage 1", "status": "Rejection Post Interview"}

        self.assertFalse(app.is_interviewed(blank_interview))
        self.assertFalse(app.is_interviewed(post_interview_rejection_blank))

    def test_csv_export_matches_canonical_stage_counts(self):
        text = app.applications_csv_text(self.sample_applications())
        rows = list(csv.DictReader(io.StringIO(text)))
        stages = [row["interview_stage"] for row in rows]

        self.assertEqual(stages.count("Screening"), 2)
        self.assertEqual(stages.count("Stage 1"), 3)
        self.assertEqual(stages.count("Stage 2"), 0)
        self.assertEqual(stages.count("Stage 3"), 0)
        self.assertEqual(sum(1 for stage in stages if stage), 5)

    def test_attach_interview_history_derives_stage_from_logged_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE interviews (id INTEGER PRIMARY KEY, application_id INTEGER, stage_name TEXT, scheduled_at TEXT)")
        conn.execute("INSERT INTO interviews (application_id, stage_name, scheduled_at) VALUES (1, 'Screening', '2026-01-01')")
        conn.execute("INSERT INTO interviews (application_id, stage_name, scheduled_at) VALUES (1, 'Stage 1', '2026-01-02')")
        apps = [{"id": 1, "interview_stage": "Screening", "status": "Rejection Post Interview"}]

        app.attach_interview_history(apps, conn)

        self.assertEqual(apps[0]["interview_count"], 2)
        self.assertEqual(apps[0]["interview_stage"], "Stage 1")
        self.assertEqual(apps[0]["reached_interview_stage"], "Stage 1")

    def test_migration_backfills_legacy_application_stage_once(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE applications (
                id INTEGER PRIMARY KEY,
                interview_stage TEXT,
                last_contact_date TEXT,
                date_applied TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE interviews (
                id INTEGER PRIMARY KEY,
                application_id INTEGER,
                stage_name TEXT,
                scheduled_at TEXT,
                interviewer_names TEXT,
                interviewer_emails TEXT,
                meeting_link TEXT,
                prep_notes TEXT,
                questions_asked TEXT,
                feedback TEXT,
                outcome TEXT,
                follow_up_sent INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE timeline_events (
                id INTEGER PRIMARY KEY,
                application_id INTEGER,
                event_date TEXT,
                event_type TEXT,
                details TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO applications (id, interview_stage, last_contact_date, date_applied)
            VALUES (1, 'Stage 2', '2026-01-03', '2026-01-01')
            """
        )

        app.migrate_interview_history(conn)
        app.migrate_interview_history(conn)

        interview_rows = conn.execute("SELECT stage_name, scheduled_at FROM interviews").fetchall()
        application = conn.execute("SELECT interview_stage FROM applications WHERE id=1").fetchone()

        self.assertEqual(len(interview_rows), 1)
        self.assertEqual(interview_rows[0]["stage_name"], "Stage 2")
        self.assertEqual(interview_rows[0]["scheduled_at"], "2026-01-03")
        self.assertEqual(application["interview_stage"], "Stage 2")


if __name__ == "__main__":
    unittest.main()
