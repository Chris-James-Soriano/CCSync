"""Import faculty, sections, and rooms from .xlsx workbooks.

Only ``.xlsx`` files are accepted. Rows that are invalid or that duplicate an
existing record are skipped and reported; valid rows are imported.

The faculty file may also carry a subject for the faculty member on the same
row (Subject Code, Subject Title, Units, Room Type, Delivery, Fixed Room).
One subject per row; repeat the faculty to add several subjects. A row whose
faculty already exists does not duplicate the faculty — its subject is added
to the existing member instead.
"""

import io
import re
import sqlite3
from contextlib import closing

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from backend.app.services.schedule_service import connect

KINDS = ("faculty", "sections", "rooms")

SUBJECT_FIELDS = ("subject_code", "subject_title", "units", "room_type", "delivery", "fixed_room")

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_ROWS = 500

XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _normalize_header(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


_HEADER_ALIASES = {
    "faculty": {
        "name": "name", "faculty": "name", "facultyname": "name", "fullname": "name",
        "status": "status",
        "weeklycapacity": "weekly_capacity", "capacity": "weekly_capacity",
        "weeklyhours": "weekly_capacity", "hours": "weekly_capacity",
        "code": "subject_code", "subject": "subject_code", "subjectcode": "subject_code",
        "title": "subject_title", "subjecttitle": "subject_title", "subjectname": "subject_title",
        "units": "units", "unit": "units", "credits": "units",
        "roomtype": "room_type", "type": "room_type",
        "delivery": "delivery", "mode": "delivery",
        "fixedroom": "fixed_room", "room": "fixed_room",
    },
    "sections": {
        "name": "name", "section": "name", "sectionname": "name",
        "year": "year", "yearlevel": "year",
        "program": "program", "course": "program",
    },
    "rooms": {
        "name": "name", "room": "name", "roomname": "name",
        "type": "type", "roomtype": "type", "classification": "type",
        "seats": "seats", "capacity": "seats", "seating": "seats",
    },
}

_REQUIRED_FIELDS = {
    "faculty": ("name",),
    "sections": ("name", "year", "program"),
    "rooms": ("name", "type", "seats"),
}

_TEMPLATE_SPECS = {
    "faculty": {
        "sheet": "Faculty",
        "filename": "ccsync-faculty-template.xlsx",
        "title": "CCSync — Faculty Import",
        "headers": ["Name", "Status", "Weekly Capacity",
                    "Subject Code", "Subject Title", "Units", "Room Type", "Delivery", "Fixed Room"],
        "examples": [
            ["Juan Dela Cruz", "Active", 40, "CSMC 401", "Machine Learning", 3, "Lecture", "In-person", ""],
            ["Juan Dela Cruz", "Active", 40, "CSMC 402", "Machine Learning Lab", 3, "Laboratory", "In-person", ""],
            ["Maria Santos", "Inactive", 24, "", "", "", "", "", ""],
        ],
        "widths": [30, 12, 18, 14, 34, 9, 13, 13, 17],
        "instructions": [
            ("Name", "Required", "Faculty member's full name, e.g. 'Juan Dela Cruz'. Must be unique. An existing faculty with the same name is not duplicated — their subjects are still imported."),
            ("Status", "Optional", "Active (default) or Inactive."),
            ("Weekly Capacity", "Optional", "Maximum teaching hours per week. Whole number, defaults to 40."),
            ("Subject Code", "Optional", "Subjects are added to this faculty member. One subject per row — repeat the same faculty on extra rows for more subjects. Must be unique."),
            ("Subject Title", "Optional", "Required when Subject Code is filled, e.g. 'Machine Learning'."),
            ("Units", "Optional", "Required when Subject Code is filled. 2, 3, or 5."),
            ("Room Type", "Optional", "Required when Subject Code is filled. Lecture, Laboratory, or Both."),
            ("Delivery", "Optional", "In-person (default) or Online. Online subjects cannot have a Fixed Room."),
            ("Fixed Room", "Optional", "Name of an existing physical room where this subject must always be scheduled, e.g. 'CCS Quadrangle'. Leave blank for any matching room. Not allowed for Online or 'Both' subjects."),
        ],
    },
    "sections": {
        "sheet": "Sections",
        "filename": "ccsync-sections-template.xlsx",
        "title": "CCSync — Sections Import",
        "headers": ["Name", "Year", "Program"],
        "examples": [
            ["BSCS 1A", 1, "BSCS"],
            ["BSIT 2B", 2, "BSIT"],
        ],
        "widths": [24, 12, 14],
        "instructions": [
            ("Name", "Required", "Section name, e.g. 'BSCS 1A'. Must be unique."),
            ("Year", "Required", "Year level: 1, 2, 3, or 4."),
            ("Program", "Required", "BSCS or BSIT."),
        ],
    },
    "rooms": {
        "sheet": "Rooms",
        "filename": "ccsync-rooms-template.xlsx",
        "title": "CCSync — Rooms Import",
        "headers": ["Name", "Type", "Seats"],
        "examples": [
            ["Room 301", "Lecture", 40],
            ["Networking Lab", "Laboratory", 36],
        ],
        "widths": [28, 16, 12],
        "instructions": [
            ("Name", "Required", "Room name, e.g. 'Room 301'. Must be unique. 'Online' is reserved and cannot be imported."),
            ("Type", "Required", "Lecture or Laboratory."),
            ("Seats", "Required", "Seating capacity. Positive whole number."),
        ],
    },
}


def build_template(kind):
    """Return (BytesIO, filename) for the .xlsx import template of ``kind``."""
    spec = _TEMPLATE_SPECS.get(kind)
    if spec is None:
        raise ValueError("Choose what to import: faculty, sections, or rooms.")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = spec["sheet"]

    header_fill = PatternFill("solid", start_color="3D0A5C", end_color="3D0A5C")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    for column, header in enumerate(spec["headers"], start=1):
        cell = sheet.cell(row=1, column=column, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row_index, example in enumerate(spec["examples"], start=2):
        for column, value in enumerate(example, start=1):
            sheet.cell(row=row_index, column=column, value=value)
    for column, width in enumerate(spec["widths"], start=1):
        sheet.column_dimensions[chr(ord("A") + column - 1)].width = width
    sheet.freeze_panes = "A2"

    notes = workbook.create_sheet("Instructions")
    notes.append(["Column", "Required", "Notes"])
    for cell in notes[1]:
        cell.fill = header_fill
        cell.font = header_font
    for row in spec["instructions"]:
        notes.append(list(row))
    notes.column_dimensions["A"].width = 20
    notes.column_dimensions["B"].width = 12
    notes.column_dimensions["C"].width = 95
    for row in notes.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    notes.freeze_panes = "A2"

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer, spec["filename"]


def _cell_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _cell_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if float(value) == number else None
    text = str(value).strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


def _existing_names(db, table):
    return {row[0].casefold() for row in db.execute(f"SELECT name FROM {table}")}


def _validate_faculty(row, existing):
    name = _cell_text(row.get("name"))
    if not name:
        return None, "Name is required."
    if len(name) > 120:
        return None, "Name is too long (max 120 characters)."
    status = _cell_text(row.get("status")) or "Active"
    status = status[:1].upper() + status[1:].lower()
    if status not in ("Active", "Inactive"):
        return None, f"Status must be Active or Inactive, not '{_cell_text(row.get('status'))}'."
    capacity_raw = _cell_text(row.get("weekly_capacity"))
    capacity = 40
    if capacity_raw:
        capacity = _cell_int(row.get("weekly_capacity"))
        if capacity is None or capacity < 1:
            return None, "Weekly Capacity must be a positive whole number."
    if name.casefold() in existing:
        return "duplicate", name
    return {"name": name, "status": status, "weekly_capacity": capacity}, None


def _validate_section(row, existing):
    name = _cell_text(row.get("name"))
    if not name:
        return None, "Name is required."
    name = re.sub(r"\s+", " ", name).upper()
    if len(name) > 40:
        return None, "Name is too long (max 40 characters)."
    year = _cell_int(row.get("year"))
    if year is None or year not in (1, 2, 3, 4):
        return None, "Year must be 1, 2, 3, or 4."
    program = _cell_text(row.get("program")).upper()
    if program not in ("BSCS", "BSIT"):
        return None, f"Program must be BSCS or BSIT, not '{_cell_text(row.get('program'))}'."
    if name.casefold() in existing:
        return "duplicate", name
    return {"name": name, "year": year, "program": program}, None


def _validate_room(row, existing):
    name = _cell_text(row.get("name"))
    if not name:
        return None, "Name is required."
    if len(name) > 80:
        return None, "Name is too long (max 80 characters)."
    if name.casefold() == "online":
        return None, "'Online' is a reserved room and cannot be imported."
    room_type = _cell_text(row.get("type")).lower()
    room_type = {"lecture": "Lecture", "laboratory": "Laboratory"}.get(room_type)
    if room_type is None:
        return None, f"Type must be Lecture or Laboratory, not '{_cell_text(row.get('type'))}'."
    seats = _cell_int(row.get("seats"))
    if seats is None or seats < 1:
        return None, "Seats must be a positive whole number."
    if name.casefold() in existing:
        return "duplicate", name
    return {"name": name, "type": room_type, "seats": seats}, None


def _validate_subject_columns(values, row_number, existing_codes):
    """Validate the optional subject columns of a faculty row.

    Returns (subject_dict_or_None, skip_or_error_message_or_None, was_skip).
    subject is None with no message when all subject columns are blank.
    """
    code = _cell_text(values.get("subject_code")).upper()
    code = re.sub(r"\s+", " ", code)
    title = _cell_text(values.get("subject_title"))
    units = _cell_int(values.get("units"))
    room_type = {"lecture": "Lecture", "laboratory": "Laboratory", "both": "Both"}.get(
        _cell_text(values.get("room_type")).lower()
    )
    delivery_raw = _cell_text(values.get("delivery")) or "In-person"
    delivery = {"inperson": "In-person", "in-person": "In-person", "online": "Online"}.get(
        delivery_raw.lower().replace(" ", "-")
    )
    if delivery is None:
        delivery = {"inperson": "In-person", "in-person": "In-person", "online": "Online"}.get(
            delivery_raw.lower().replace("-", "")
        )
    fixed_room = _cell_text(values.get("fixed_room"))

    if code.casefold() in existing_codes:
        return None, f"Row {row_number}: subject {code} already exists.", True
    if not code:
        return None, f"Row {row_number}: Subject Code is required when any subject column is filled, e.g. 'CSMC 401'.", False
    if len(code) > 20:
        return None, f"Row {row_number}: Subject Code is too long (max 20 characters).", False
    if not title:
        return None, f"Row {row_number}: Subject Title is required when Subject Code is filled.", False
    if len(title) > 120:
        return None, f"Row {row_number}: Subject Title is too long (max 120 characters).", False
    if units not in (2, 3, 5):
        return None, f"Row {row_number}: Units must be 2, 3, or 5.", False
    if room_type is None:
        return None, f"Row {row_number}: Room Type must be Lecture, Laboratory, or Both.", False
    if delivery is None:
        return None, f"Row {row_number}: Delivery must be In-person or Online.", False
    if delivery == "Online" and fixed_room:
        return None, f"Row {row_number}: Online subjects cannot be given a Fixed Room.", False
    if delivery != "Online" and room_type == "Both" and fixed_room:
        return None, f"Row {row_number}: a 'Both' subject cannot be fixed to one room.", False

    return (
        {
            "code": code,
            "title": title,
            "units": units,
            "room_type": room_type,
            "delivery": delivery,
            "fixed_room": fixed_room,
        },
        None,
        False,
    )


def _import_faculty(db, rows, column_map):
    """Faculty import with optional embedded subject per row."""
    imported, skipped, errors, seen = 0, [], [], 0
    new_records = []
    staged = {}  # casefold name -> planned id holder {'record': record, 'id': None}
    existing_ids = {}
    subject_codes = {row[0].casefold() for row in db.execute("SELECT code FROM subjects")}
    physical_rooms = {
        row["name"].casefold(): row["id"]
        for row in db.execute(
            "SELECT id, name FROM rooms WHERE lower(name) != 'online'"
        )
    }
    existing_names = _existing_names(db, "faculty")
    subject_jobs = []
    subjects_imported, subjects_skipped, subjects_errors, subjects_seen = 0, [], [], 0

    def faculty_id_for(casefold_name):
        if casefold_name in staged:
            return None  # resolved after insert
        if casefold_name not in existing_ids:
            row = db.execute(
                "SELECT id FROM faculty WHERE lower(name) = ?", (casefold_name,)
            ).fetchone()
            existing_ids[casefold_name] = row[0] if row else None
        return existing_ids[casefold_name]

    for row_number, row in enumerate(rows, start=2):
        if row_number - 1 > MAX_ROWS:
            errors.append(f"Row {row_number}: import stopped after {MAX_ROWS} rows.")
            break
        values = {
            field: row[index] if index < len(row) else None
            for field, index in column_map.items()
        }
        if all(_cell_text(value) == "" for value in values.values()):
            continue
        seen += 1

        has_subject = any(_cell_text(values.get(field)) for field in SUBJECT_FIELDS)
        key = _cell_text(values.get("name")).casefold()

        record, problem = _validate_faculty(values, existing_names)
        if record == "duplicate":
            if not has_subject:
                skipped.append(f"Row {row_number}: {problem} already exists.")
                continue
        elif problem:
            errors.append(f"Row {row_number}: {problem}")
            continue
        else:
            new_records.append(record)
            staged[record["name"].casefold()] = {"record": record}
            existing_names.add(record["name"].casefold())

        if has_subject:
            subjects_seen += 1
            subject, subject_problem, was_skip = _validate_subject_columns(
                values, row_number, subject_codes
            )
            if subject is not None:
                fixed_room = subject.pop("fixed_room")
                room_id = None
                if fixed_room:
                    room_id = physical_rooms.get(fixed_room.casefold())
                    if room_id is None:
                        subjects_errors.append(
                            f"Row {row_number}: Fixed Room '{fixed_room}' was not found."
                        )
                        continue
                subject_codes.add(subject["code"].casefold())
                subject_jobs.append(
                    {"row": row_number, "faculty_key": key, "faculty_id": faculty_id_for(key),
                     "subject": subject, "room_id": room_id}
                )
            elif was_skip:
                subjects_skipped.append(subject_problem)
            else:
                subjects_errors.append(subject_problem)

    for record in new_records:
        cursor = db.execute(
            _INSERT_SQL["faculty"], _row_values("faculty", record)
        )
        staged[record["name"].casefold()]["id"] = cursor.lastrowid
        imported += 1
    db.commit()  # make new faculty visible to add_subject's connection

    for job in subject_jobs:
        faculty_id = job["faculty_id"]
        if faculty_id is None:
            faculty_id = staged[job["faculty_key"]]["id"]
        try:
            from backend.app.services.schedule_service import add_subject

            add_subject(
                faculty_id, job["subject"]["code"], job["subject"]["title"],
                job["subject"]["units"], job["subject"]["room_type"],
                job["subject"]["delivery"], job["room_id"],
            )
            subjects_imported += 1
        except ValueError as error:
            subjects_errors.append(f"Row {job['row']}: {error}")

    return {
        "kind": "faculty",
        "imported": imported,
        "skipped": len(skipped),
        "skipped_rows": skipped,
        "errors": errors,
        "seen": seen,
        "subjects": {
            "imported": subjects_imported,
            "skipped": len(subjects_skipped),
            "skipped_rows": subjects_skipped,
            "errors": subjects_errors,
            "seen": subjects_seen,
        },
    }


_VALIDATORS = {
    "faculty": _validate_faculty,
    "sections": _validate_section,
    "rooms": _validate_room,
}

_TABLES = {
    "faculty": "faculty",
    "sections": "sections",
    "rooms": "rooms",
}

_INSERT_SQL = {
    "faculty": "INSERT INTO faculty(name, status, weekly_capacity) VALUES (?, ?, ?)",
    "sections": "INSERT INTO sections(name, year, program) VALUES (?, ?, ?)",
    "rooms": "INSERT INTO rooms(name, type, seats) VALUES (?, ?, ?)",
}


def _row_values(kind, record):
    if kind == "faculty":
        return (record["name"], record["status"], record["weekly_capacity"])
    if kind == "sections":
        return (record["name"], record["year"], record["program"])
    return (record["name"], record["type"], record["seats"])


def import_xlsx(kind, upload):
    """Import rows from an uploaded .xlsx file.

    Returns a dict with imported/skipped/errors/total counts plus detail lists.
    Raises ValueError for file-level problems (wrong extension, unreadable file,
    missing required columns).
    """
    if kind not in KINDS:
        raise ValueError("Choose what to import: faculty, sections, or rooms.")

    filename = (upload.filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Only .xlsx files are accepted. Save your spreadsheet as .xlsx and try again.")

    data = upload.read()
    if not data:
        raise ValueError("The uploaded file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("The file is too large. Maximum size is 2 MB.")

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as error:
        raise ValueError("That file could not be read as an .xlsx workbook.") from error

    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration as error:
        raise ValueError("The workbook is empty. Download the template to see the expected format.") from error

    aliases = _HEADER_ALIASES[kind]
    column_map = {}
    for index, raw in enumerate(header_row):
        field = aliases.get(_normalize_header(raw))
        if field and field not in column_map:
            column_map[field] = index

    missing = [field for field in _REQUIRED_FIELDS[kind] if field not in column_map]
    if missing:
        labels = {"name": "Name", "year": "Year", "program": "Program", "type": "Type", "seats": "Seats"}
        raise ValueError(
            "Missing required column(s): " + ", ".join(labels[field] for field in missing)
            + ". Download the template to see the expected format."
        )

    validator = _VALIDATORS[kind]
    table = _TABLES[kind]
    imported, skipped, errors, seen = 0, [], [], 0
    records = []

    with closing(connect()) as db:
        if kind == "faculty":
            try:
                return _import_faculty(db, rows, column_map)
            except sqlite3.IntegrityError as error:
                db.rollback()
                raise ValueError(f"Import failed while saving: {error}") from error

        existing = _existing_names(db, table)
        for row_number, row in enumerate(rows, start=2):
            if row_number - 1 > MAX_ROWS:
                errors.append(f"Row {row_number}: import stopped after {MAX_ROWS} rows.")
                break
            values = {field: row[index] if index < len(row) else None for field, index in column_map.items()}
            if all(_cell_text(value) == "" for value in values.values()):
                continue  # skip blank rows
            seen += 1
            record, problem = validator(values, existing)
            if record == "duplicate":
                skipped.append(f"Row {row_number}: {problem} already exists.")
                continue
            if problem:
                errors.append(f"Row {row_number}: {problem}")
                continue
            existing.add(record["name"].casefold())
            records.append(record)
        if records:
            try:
                db.executemany(_INSERT_SQL[kind], [_row_values(kind, record) for record in records])
                db.commit()
                imported = len(records)
            except sqlite3.IntegrityError as error:
                db.rollback()
                raise ValueError(f"Import failed while saving: {error}") from error

    return {
        "kind": kind,
        "imported": imported,
        "skipped": len(skipped),
        "skipped_rows": skipped,
        "errors": errors,
        "seen": seen,
    }
