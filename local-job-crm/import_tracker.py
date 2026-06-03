#!/usr/bin/env python3
import csv
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import app

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
EXCEL_EPOCH_OFFSET = 693594


def column_index(cell_ref):
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + ord(char.upper()) - 64
    return value - 1


def shared_strings(zf):
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for item in root.findall("a:si", NS):
        text = "".join(node.text or "" for node in item.findall(".//a:t", NS))
        strings.append(text)
    return strings


def workbook_sheets(zf):
    root = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    sheets = []
    for sheet in root.findall("a:sheets/a:sheet", NS):
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rel_map[rel_id].lstrip("/")
        if target.startswith("xl/"):
            sheet_path = target
        else:
            sheet_path = f"xl/{target.replace('../', '')}"
        sheets.append((sheet.attrib["name"], sheet_path))
    return sheets


def read_xlsx(path):
    with zipfile.ZipFile(path) as zf:
        strings = shared_strings(zf)
        sheets = workbook_sheets(zf)
        sheet_path = next((target for name, target in sheets if "tracker" in name.lower() or "job" in name.lower()), sheets[0][1])
        root = ET.fromstring(zf.read(sheet_path))
        rows = []
        for row in root.findall("a:sheetData/a:row", NS):
            values = []
            for cell in row.findall("a:c", NS):
                idx = column_index(cell.attrib.get("r", "A1"))
                while len(values) <= idx:
                    values.append("")
                raw = cell.find("a:v", NS)
                value = raw.text if raw is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = strings[int(value)]
                values[idx] = value
            rows.append(values)
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in rows[1:] if any(row)]


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def excel_date(value):
    if value in (None, ""):
        return ""
    text = str(value).strip()
    parsed = app.parse_date(text)
    if parsed:
        return parsed.isoformat()
    try:
        serial = int(float(text))
    except ValueError:
        return text
    if 30000 <= serial <= 60000:
        return app.date.fromordinal(serial + EXCEL_EPOCH_OFFSET).isoformat()
    return text


def normalize_route(value):
    text = (value or "").strip()
    lowered = text.lower()
    if "sap" in lowered or "erp" in lowered:
        return "General"
    if "service" in lowered or "delivery" in lowered:
        return "Service Delivery"
    if "governance" in lowered or "operation" in lowered or "commercial" in lowered:
        return "Operations"
    return text


def convert_row(raw):
    return {
        "company": raw.get("Company") or raw.get("company") or "",
        "role_title": raw.get("Title") or raw.get("Role") or raw.get("role_title") or "",
        "date_applied": excel_date(raw.get("Date Applied") or raw.get("Date") or raw.get("date_applied") or app.today_iso()),
        "status": app.normalize_status(raw.get("Stage") or raw.get("Status") or raw.get("status") or app.DEFAULT_STATUS),
        "last_contact_date": excel_date(raw.get("Last Update") or raw.get("last_contact_date") or ""),
        "source": raw.get("Source") or raw.get("source") or "",
        "next_action": raw.get("Next Action") or raw.get("next_action") or "",
        "follow_up_date": excel_date(raw.get("Follow-up Date") or raw.get("follow_up_date") or ""),
        "location": raw.get("Location/Remote") or raw.get("Location") or raw.get("location") or "",
        "job_url": raw.get("Application URL") or raw.get("Job URL") or raw.get("job_url") or "",
        "salary": raw.get("Salary") or raw.get("Salary Estimate") or raw.get("salary") or "",
        "cv_route": normalize_route(raw.get("Best CV Route") or raw.get("CV Route") or raw.get("cv_route") or ""),
        "fit_score": raw.get("Market Fit %") or raw.get("Fit Score") or raw.get("fit_score") or "",
        "notes": raw.get("Comments") or raw.get("Projection Notes") or raw.get("Notes") or "",
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 import_tracker.py /path/to/applications.xlsx")
        raise SystemExit(2)
    path = Path(sys.argv[1])
    app.init_db()
    rows = read_xlsx(path) if path.suffix.lower() == ".xlsx" else read_csv(path)
    imported = 0
    for row in rows:
        payload = convert_row(row)
        if payload["company"] and payload["role_title"]:
            app.create_application(payload)
            imported += 1
    print(f"Imported {imported} applications into {app.DB_PATH}")


if __name__ == "__main__":
    main()
