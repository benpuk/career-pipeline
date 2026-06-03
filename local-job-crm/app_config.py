import os


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


APP_CONFIG = {
    "app": {
        "name": os.environ.get("NEXT_PUBLIC_APP_NAME", "Job Application Tracker"),
        "description": "A lightweight tracker for managing job applications, follow-ups, ghosting, interviews, rejections, and pipeline health.",
        "owner": "Ben Picot",
        "copyrightYear": 2026,
    },
    # Business logic: these values control when an active application is treated
    # as potentially ghosted. Contact resets the counter to last_contact_date.
    "tracking": {
        "ghostingThresholdDays": env_int("NEXT_PUBLIC_GHOSTING_THRESHOLD_DAYS", 21),
        "warningThresholdDays": 14,
        "resetGhostingCounterOnContact": True,
        "useSuggestedGhosting": False,
    },
    "statuses": {
        "active": ["In Progress", "Interview", "Offer Pending"],
        "closed": ["Rejected", "Rejected Post Interview", "Ghosted", "Withdrawn", "Offer Accepted"],
        "defaultStatus": "In Progress",
    },
    "display": {
        "dateFormat": "dd/MM/yyyy",
        "currency": os.environ.get("NEXT_PUBLIC_DEFAULT_CURRENCY", "GBP"),
    },
    "storage": {
        "applicationStorageKey": "jobApplicationTracker.applications",
        "settingsStorageKey": "jobApplicationTracker.settings",
    },
    "features": {
        "enableDemoData": env_bool("NEXT_PUBLIC_ENABLE_DEMO_DATA", False),
        "enableCsvExport": True,
        "enableCsvImport": False,
        "enableAnalytics": True,
        "enableCommercialBranding": False,
    },
    "urls": {
        "homepage": "",
        "support": "",
        "commercialLicensing": "",
    },
    "licence": {
        "type": "Personal Use Only",
        "commercialUseAllowed": False,
        "commercialLicenceRequired": True,
    },
}

STATUSES = [
    APP_CONFIG["statuses"]["defaultStatus"],
    "Interview",
    "Offer Pending",
    "Rejected",
    "Rejected Post Interview",
    "Ghosted",
    "Withdrawn",
    "Offer Accepted",
]

ACTIVE_STATUSES = set(APP_CONFIG["statuses"]["active"])
CLOSED_STATUSES = set(APP_CONFIG["statuses"]["closed"])
INTERVIEW_STATUSES = {"Interview"}
DEFAULT_STATUS = APP_CONFIG["statuses"]["defaultStatus"]
GHOSTING_THRESHOLD_DAYS = APP_CONFIG["tracking"]["ghostingThresholdDays"]
WARNING_THRESHOLD_DAYS = APP_CONFIG["tracking"]["warningThresholdDays"]

CV_ROUTES = [
    "General",
    "Operations",
    "Service Delivery",
]

LEGACY_STATUS_MAP = {
    "Rejection": "Rejected",
    "Rejection Post Interview": "Rejected Post Interview",
    "Screening Completed": "Interview",
    "1st Interview Completed": "Interview",
    "2nd Interview Completed": "Interview",
    "Offer": "Offer Accepted",
}
