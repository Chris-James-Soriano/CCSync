"""Backup and restore of the whole CCSync data store, plus a factory reset.

``build_backup`` produces one ``.xlsx`` workbook containing the schedule,
faculty, subjects, sections, rooms, and section-subject assignments (never
user accounts or password hashes). ``restore_backup`` validates the file
completely first, then replaces all current data inside a single transaction,
so a bad file changes nothing. ``delete_schedule`` removes every scheduled
block; all other data — including accounts — is kept.
"""

import io
import re
from contextlib import closing
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from backend.app.services.schedule_service import connect

XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_ROWS = 5000

STYLE_HEADER_FILL = "3D0A5C"
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _cell_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _cell_number(value, *, integer=False):
    """Parse a spreadsheet number cell. Returns None when not a number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if integer and number != int(number):
        return None
    if not integer and abs(number * 2 - round(number * 2)) > 1e-9:
        return None  # times are stored in 30-minute steps
    return int(number) if integer else number


def _header_map(header_row):
    mapping = {}
    for index, raw in enumerate(header_row or ()):
        label = re.sub(r"[^a-z0-9]", "", str(raw or "").strip().lower())
        if label and label not in mapping:
            mapping[label] = index
    return mapping


def _sheet_rows(workbook, sheet_name):
    if sheet_name not in workbook.sheetnames:
        return None  # sheet missing entirely
    sheet = workbook[sheet_name]
    rows = sheet.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration:
        return [], {}
    mapping = _header_map(header)
    return list(rows), mapping


def _fit(sheet, headers, rows, widths):
    header_fill = PatternFill("solid", start_color=STYLE_HEADER_FILL, end_color=STYLE_HEADER_FILL)
    header_font = Font(bold=True, color="FFFFFF", size=12)
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=column, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row_index, row in enumerate(rows, start=2):
        for column, value in enumerate(row, start=1):
            sheet.cell(row=row_index, column=column, value=value)
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(ord("A") + column - 1)].width = width
    sheet.freeze_panes = "A2"


def build_backup():
    """Return (BytesIO, filename) with the full backup workbook."""
    with closing(connect()) as db:
        rooms = [
            dict(row) for row in db.execute(
                "SELECT name, type, seats FROM rooms WHERE lower(name) != 'online' ORDER BY name"
            )
        ]
        faculty = [
            dict(row) for row in db.execute(
                "SELECT name, status, weekly_capacity FROM faculty ORDER BY name"
            )
        ]
        subjects = [
            dict(row) for row in db.execute(
                "SELECT s.code, s.title, s.units, s.room_type, s.delivery, "
                "f.name AS faculty, r.name AS fixed_room "
                "FROM subjects s JOIN faculty f ON f.id = s.faculty_id "
                "LEFT JOIN rooms r ON r.id = s.room_id ORDER BY s.code"
            )
        ]
        sections = [
            dict(row) for row in db.execute(
                "SELECT name, year, program FROM sections ORDER BY name"
            )
        ]
        section_subjects = [
            dict(row) for row in db.execute(
                "SELECT se.name AS section, s.code AS subject_code "
                "FROM section_subjects ss JOIN sections se ON se.id = ss.section_id "
                "JOIN subjects s ON s.id = ss.subject_id ORDER BY se.name, s.code"
            )
        ]
        schedule = [
            dict(row) for row in db.execute(
                "SELECT se.name AS section, s.code AS subject_code, f.name AS faculty, "
                "sc.day, sc.start, sc.end, sc.session_type, r.name AS room "
                "FROM schedules sc JOIN sections se ON se.id = sc.section_id "
                "JOIN subjects s ON s.id = sc.subject_id JOIN faculty f ON f.id = s.faculty_id "
                "JOIN rooms r ON r.id = sc.room_id "
                "ORDER BY sc.day, sc.start, se.name"
            )
        ]

    workbook = Workbook()
    workbook.remove(workbook.active)

    notes = workbook.create_sheet("Instructions")
    notes.append(["CCSync — Master Schedule Backup"])
    notes["A1"].font = Font(bold=True, size=16, color=STYLE_HEADER_FILL)
    for line in (
        f"Created: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "Contains: the master schedule, faculty, subjects, sections, rooms, and section-subject assignments.",
        "User accounts and passwords are NOT included in this file.",
        "",
        "To restore: Settings -> Import backup, choose this file.",
        "Restoring REPLACES all current data (schedule, faculty, subjects, sections, rooms).",
        "User accounts are kept, so you will stay signed in. The reserved 'Online' room is recreated if missing.",
        "Do not edit the sheet names or the header rows.",
    ):
        notes.append([line])
    notes.column_dimensions["A"].width = 110

    _fit(
        workbook.create_sheet("Rooms"),
        ["Name", "Type", "Seats"],
        [[r["name"], r["type"], r["seats"]] for r in rooms],
        [28, 16, 10],
    )
    _fit(
        workbook.create_sheet("Faculty"),
        ["Name", "Status", "Weekly Capacity"],
        [[f["name"], f["status"], f["weekly_capacity"]] for f in faculty],
        [34, 12, 18],
    )
    _fit(
        workbook.create_sheet("Subjects"),
        ["Code", "Title", "Units", "Room Type", "Delivery", "Faculty", "Fixed Room"],
        [[s["code"], s["title"], s["units"], s["room_type"], s["delivery"], s["faculty"], s["fixed_room"] or ""] for s in subjects],
        [16, 36, 9, 14, 13, 30, 18],
    )
    _fit(
        workbook.create_sheet("Sections"),
        ["Name", "Year", "Program"],
        [[s["name"], s["year"], s["program"]] for s in sections],
        [20, 8, 12],
    )
    _fit(
        workbook.create_sheet("SectionSubjects"),
        ["Section", "Subject Code"],
        [[ss["section"], ss["subject_code"]] for ss in section_subjects],
        [20, 18],
    )
    _fit(
        workbook.create_sheet("Schedule"),
        ["Section", "Subject Code", "Faculty", "Day", "Start", "End", "Session Type", "Room"],
        [[sc["section"], sc["subject_code"], sc["faculty"], sc["day"], sc["start"], sc["end"],
          sc["session_type"], sc["room"]] for sc in schedule],
        [16, 16, 26, 8, 9, 9, 15, 20],
    )

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer, f"ccsync-backup-{datetime.now():%Y%m%d-%H%M%S}.xlsx"


def _unique(values, label, problems, row_number):
    seen = set()
    ok = []
    for value in values:
        if value.casefold() in seen:
            problems.append(f"Row {row_number}: duplicate {label} '{value}'.")
        else:
            seen.add(value.casefold())
            ok.append(value)
    return ok


def _parse_rooms(workbook, problems):
    parsed = _sheet_rows(workbook, "Rooms")
    if parsed is None:
        problems.append("The 'Rooms' sheet is missing.")
        return []
    rows, mapping = parsed
    for field in ("name", "type", "seats"):
        if field not in mapping:
            problems.append(f"The 'Rooms' sheet is missing its '{field.title()}' column.")
    if rows == [] and mapping == {}:
        return []
    records = []
    for offset, row in enumerate(rows, start=2):
        if not row or all(_cell_text(v) == "" for v in row):
            continue
        name = _cell_text(row[mapping["name"]] if "name" in mapping else None)
        room_type = {"lecture": "Lecture", "laboratory": "Laboratory"}.get(
            _cell_text(row[mapping["type"]] if "type" in mapping else None).lower()
        )
        seats = _cell_number(row[mapping["seats"]] if "seats" in mapping else None, integer=True)
        if not name:
            problems.append(f"Rooms row {offset}: Name is required.")
            continue
        if name.casefold() == "online":
            continue  # reserved pseudo-room, recreated automatically
        if room_type is None:
            problems.append(f"Rooms row {offset}: Type must be Lecture or Laboratory.")
            continue
        if seats is None or seats < 1:
            problems.append(f"Rooms row {offset}: Seats must be a positive whole number.")
            continue
        records.append({"name": name, "type": room_type, "seats": seats})
    names = [r["name"] for r in records]
    if len({n.casefold() for n in names}) != len(names):
        problems.append("The 'Rooms' sheet contains duplicate room names.")
    return records


def _parse_faculty(workbook, problems):
    parsed = _sheet_rows(workbook, "Faculty")
    if parsed is None:
        problems.append("The 'Faculty' sheet is missing.")
        return []
    rows, mapping = parsed
    for field in ("name",):
        if field not in mapping:
            problems.append("The 'Faculty' sheet is missing its 'Name' column.")
    records = []
    for offset, row in enumerate(rows, start=2):
        if not row or all(_cell_text(v) == "" for v in row):
            continue
        name = _cell_text(row[mapping["name"]] if "name" in mapping else None)
        if not name:
            problems.append(f"Faculty row {offset}: Name is required.")
            continue
        status = _cell_text(row[mapping["status"]] if "status" in mapping else None) or "Active"
        status = status[:1].upper() + status[1:].lower()
        if status not in ("Active", "Inactive"):
            problems.append(f"Faculty row {offset}: Status must be Active or Inactive.")
            continue
        capacity = 40
        if "weeklycapacity" in mapping:
            raw = _cell_text(row[mapping["weeklycapacity"]])
            if raw:
                capacity = _cell_number(row[mapping["weeklycapacity"]], integer=True)
                if capacity is None or capacity < 1:
                    problems.append(f"Faculty row {offset}: Weekly Capacity must be a positive whole number.")
                    continue
        records.append({"name": name, "status": status, "weekly_capacity": capacity})
    names = [r["name"] for r in records]
    if len({n.casefold() for n in names}) != len(names):
        problems.append("The 'Faculty' sheet contains duplicate faculty names.")
    return records


def _parse_sections(workbook, problems):
    parsed = _sheet_rows(workbook, "Sections")
    if parsed is None:
        problems.append("The 'Sections' sheet is missing.")
        return []
    rows, mapping = parsed
    for field in ("name", "year", "program"):
        if field not in mapping:
            problems.append(f"The 'Sections' sheet is missing its '{field.title()}' column.")
    records = []
    for offset, row in enumerate(rows, start=2):
        if not row or all(_cell_text(v) == "" for v in row):
            continue
        name = re.sub(r"\s+", " ", _cell_text(row[mapping["name"]] if "name" in mapping else None)).upper()
        year = _cell_number(row[mapping["year"]] if "year" in mapping else None, integer=True)
        program = _cell_text(row[mapping["program"]] if "program" in mapping else None).upper()
        if not name:
            problems.append(f"Sections row {offset}: Name is required.")
            continue
        if year not in (1, 2, 3, 4):
            problems.append(f"Sections row {offset}: Year must be 1, 2, 3, or 4.")
            continue
        if program not in ("BSCS", "BSIT"):
            problems.append(f"Sections row {offset}: Program must be BSCS or BSIT.")
            continue
        records.append({"name": name, "year": year, "program": program})
    names = [r["name"] for r in records]
    if len({n.casefold() for n in names}) != len(names):
        problems.append("The 'Sections' sheet contains duplicate section names.")
    return records


def _parse_subjects(workbook, problems, faculty_names, room_names):
    parsed = _sheet_rows(workbook, "Subjects")
    if parsed is None:
        problems.append("The 'Subjects' sheet is missing.")
        return []
    rows, mapping = parsed
    for field in ("code", "title", "units", "roomtype", "delivery", "faculty"):
        if field not in mapping:
            problems.append(f"The 'Subjects' sheet is missing a required column ('{field}').")
    records = []
    for offset, row in enumerate(rows, start=2):
        if not row or all(_cell_text(v) == "" for v in row):
            continue
        code = re.sub(r"\s+", " ", _cell_text(row[mapping["code"]] if "code" in mapping else None).upper())
        title = _cell_text(row[mapping["title"]] if "title" in mapping else None)
        units = _cell_number(row[mapping["units"]] if "units" in mapping else None, integer=True)
        room_type = {"lecture": "Lecture", "laboratory": "Laboratory", "both": "Both"}.get(
            _cell_text(row[mapping["roomtype"]] if "roomtype" in mapping else None).lower()
        )
        delivery_raw = _cell_text(row[mapping["delivery"]] if "delivery" in mapping else None) or "In-person"
        delivery = {"inperson": "In-person", "in-person": "In-person", "online": "Online"}.get(
            delivery_raw.lower().replace(" ", "-")
        )
        faculty_name = _cell_text(row[mapping["faculty"]] if "faculty" in mapping else None)
        fixed_room = _cell_text(row[mapping["fixedroom"]] if "fixedroom" in mapping else None)

        if not code:
            problems.append(f"Subjects row {offset}: Code is required.")
            continue
        if not title:
            problems.append(f"Subjects row {offset}: Title is required.")
            continue
        if units not in (2, 3, 5):
            problems.append(f"Subjects row {offset}: Units must be 2, 3, or 5.")
            continue
        if room_type is None:
            problems.append(f"Subjects row {offset}: Room Type must be Lecture, Laboratory, or Both.")
            continue
        if delivery is None:
            problems.append(f"Subjects row {offset}: Delivery must be In-person or Online.")
            continue
        if faculty_name.casefold() not in faculty_names:
            problems.append(f"Subjects row {offset}: faculty '{faculty_name}' is not in the 'Faculty' sheet.")
            continue
        if delivery == "Online" and fixed_room:
            problems.append(f"Subjects row {offset}: Online subjects cannot be given a Fixed Room.")
            continue
        if room_type == "Both" and fixed_room:
            problems.append(f"Subjects row {offset}: a 'Both' subject cannot be fixed to one room.")
            continue
        if fixed_room:
            if fixed_room.casefold() not in room_names:
                problems.append(f"Subjects row {offset}: Fixed Room '{fixed_room}' is not in the 'Rooms' sheet.")
                continue
        records.append({
            "code": code, "title": title, "units": units, "room_type": room_type,
            "delivery": delivery, "faculty": faculty_name, "fixed_room": fixed_room or "",
        })
    codes = [r["code"] for r in records]
    if len({c.casefold() for c in codes}) != len(codes):
        problems.append("The 'Subjects' sheet contains duplicate subject codes.")
    return records


def _parse_section_subjects(workbook, problems, section_names, subject_codes):
    parsed = _sheet_rows(workbook, "SectionSubjects")
    if parsed is None:
        return []  # optional sheet
    rows, mapping = parsed
    if "section" not in mapping or "subjectcode" not in mapping:
        problems.append("The 'SectionSubjects' sheet needs 'Section' and 'Subject Code' columns.")
        return []
    records = []
    seen = set()
    for offset, row in enumerate(rows, start=2):
        if not row or all(_cell_text(v) == "" for v in row):
            continue
        section = _cell_text(row[mapping["section"]])
        code = _cell_text(row[mapping["subjectcode"]]).upper()
        if section.casefold() not in section_names:
            problems.append(f"SectionSubjects row {offset}: section '{section}' is not in the 'Sections' sheet.")
            continue
        if code.casefold() not in subject_codes:
            problems.append(f"SectionSubjects row {offset}: subject '{code}' is not in the 'Subjects' sheet.")
            continue
        key = (section.casefold(), code.casefold())
        if key in seen:
            continue  # duplicates in this sheet are harmless, keep one
        seen.add(key)
        records.append({"section": section, "subject_code": code})
    return records


def _parse_schedule(workbook, problems, section_names, subject_codes, room_names):
    parsed = _sheet_rows(workbook, "Schedule")
    if parsed is None:
        return []  # optional sheet
    rows, mapping = parsed
    for field in ("section", "subjectcode", "day", "start", "end", "sessiontype"):
        if field not in mapping:
            problems.append(f"The 'Schedule' sheet is missing a required column ('{field}').")
    records = []
    for offset, row in enumerate(rows, start=2):
        if not row or all(_cell_text(v) == "" for v in row):
            continue
        section = _cell_text(row[mapping["section"]] if "section" in mapping else None)
        code = re.sub(r"\s+", " ", _cell_text(row[mapping["subjectcode"]] if "subjectcode" in mapping else None).upper())
        day = _cell_text(row[mapping["day"]] if "day" in mapping else None).upper()[:3]
        start = _cell_number(row[mapping["start"]] if "start" in mapping else None)
        end = _cell_number(row[mapping["end"]] if "end" in mapping else None)
        session_type = {"lecture": "Lecture", "laboratory": "Laboratory", "online": "Online"}.get(
            _cell_text(row[mapping["sessiontype"]] if "sessiontype" in mapping else None).lower()
        )
        room = _cell_text(row[mapping["room"]] if "room" in mapping else None)

        if section.casefold() not in section_names:
            problems.append(f"Schedule row {offset}: section '{section}' is not in the 'Sections' sheet.")
            continue
        if code.casefold() not in subject_codes:
            problems.append(f"Schedule row {offset}: subject '{code}' is not in the 'Subjects' sheet.")
            continue
        if day not in DAYS:
            problems.append(f"Schedule row {offset}: Day must be one of {', '.join(DAYS)}.")
            continue
        if start is None or end is None or not (7 <= start < end <= 17):
            problems.append(f"Schedule row {offset}: Start/End must be 7 to 17 and End must be after Start.")
            continue
        if session_type is None:
            problems.append(f"Schedule row {offset}: Session Type must be Lecture, Laboratory, or Online.")
            continue
        if session_type != "Online" and room:
            if room.casefold() not in room_names:
                problems.append(f"Schedule row {offset}: room '{room}' is not in the 'Rooms' sheet.")
                continue
        records.append({
            "section": section, "subject_code": code, "day": day,
            "start": start, "end": end, "session_type": session_type, "room": room,
        })
    return records


def restore_backup(upload):
    """Replace all current data with the contents of the uploaded backup.

    Raises ValueError with a precise message and changes nothing when the
    file is invalid. Returns a counts dict on success.
    """
    filename = (upload.filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Only .xlsx backup files are accepted.")

    data = upload.read()
    if not data:
        raise ValueError("The uploaded file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("The file is too large. Maximum size is 5 MB.")

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as error:
        raise ValueError("That file could not be read as an .xlsx workbook.") from error

    problems = []
    rooms = _parse_rooms(workbook, problems)
    faculty = _parse_faculty(workbook, problems)
    sections = _parse_sections(workbook, problems)
    faculty_names = {f["name"].casefold() for f in faculty}
    room_names = {r["name"].casefold() for r in rooms}
    subjects = _parse_subjects(workbook, problems, faculty_names, room_names)
    section_names = {s["name"].casefold() for s in sections}
    subject_codes = {s["code"].casefold() for s in subjects}
    section_subjects = _parse_section_subjects(workbook, problems, section_names, subject_codes)
    schedule = _parse_schedule(workbook, problems, section_names, subject_codes, room_names)
    if len(rooms) + len(faculty) + len(sections) + len(subjects) > MAX_ROWS:
        problems.append(f"Too many rows. A backup may hold at most {MAX_ROWS} records.")
    if problems:
        detail = "; ".join(problems[:8])
        if len(problems) > 8:
            detail += f"; …and {len(problems) - 8} more problem(s)"
        raise ValueError(f"The backup is invalid and nothing was changed: {detail}")

    with closing(connect()) as db:
        try:
            db.execute("BEGIN")
            online = db.execute(
                "SELECT id FROM rooms WHERE lower(name) = 'online'"
            ).fetchone()
            if online:
                online_id = online[0]
            else:
                online_id = db.execute(
                    "INSERT INTO rooms(name, type, seats) VALUES ('Online', 'Lecture', 9999)"
                ).lastrowid

            db.execute("DELETE FROM schedules")
            db.execute("DELETE FROM section_subjects")
            db.execute("DELETE FROM subjects")
            db.execute("DELETE FROM sections")
            db.execute("DELETE FROM faculty")
            db.execute("DELETE FROM rooms WHERE lower(name) != 'online'")

            room_ids = {}
            for room in rooms:
                cursor = db.execute(
                    "INSERT INTO rooms(name, type, seats) VALUES (?, ?, ?)",
                    (room["name"], room["type"], room["seats"]),
                )
                room_ids[room["name"].casefold()] = cursor.lastrowid

            faculty_ids = {}
            for member in faculty:
                cursor = db.execute(
                    "INSERT INTO faculty(name, status, weekly_capacity) VALUES (?, ?, ?)",
                    (member["name"], member["status"], member["weekly_capacity"]),
                )
                faculty_ids[member["name"].casefold()] = cursor.lastrowid

            subject_ids = {}
            subject_meta = {}
            for subject in subjects:
                room_id = room_ids.get(subject["fixed_room"].casefold()) if subject["fixed_room"] else None
                faculty_id = faculty_ids[subject["faculty"].casefold()]
                cursor = db.execute(
                    "INSERT INTO subjects(code, title, units, room_type, faculty_id, delivery, room_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (subject["code"], subject["title"], subject["units"], subject["room_type"],
                     faculty_id, subject["delivery"], room_id),
                )
                subject_ids[subject["code"].casefold()] = cursor.lastrowid
                subject_meta[subject["code"].casefold()] = (faculty_id, subject["delivery"])

            section_ids = {}
            for section in sections:
                cursor = db.execute(
                    "INSERT INTO sections(name, year, program) VALUES (?, ?, ?)",
                    (section["name"], section["year"], section["program"]),
                )
                section_ids[section["name"].casefold()] = cursor.lastrowid

            for link in section_subjects:
                db.execute(
                    "INSERT OR IGNORE INTO section_subjects(section_id, subject_id) VALUES (?, ?)",
                    (section_ids[link["section"].casefold()], subject_ids[link["subject_code"].casefold()]),
                )

            for block in schedule:
                faculty_id, delivery = subject_meta[block["subject_code"].casefold()]
                room_id = online_id
                if block["session_type"] != "Online" and delivery != "Online" and block["room"]:
                    room_id = room_ids.get(block["room"].casefold(), online_id)
                db.execute(
                    "INSERT INTO schedules(subject_id, section_id, faculty_id, room_id, day, start, end, session_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (subject_ids[block["subject_code"].casefold()], section_ids[block["section"].casefold()],
                     faculty_id, room_id, block["day"], block["start"], block["end"], block["session_type"]),
                )
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "rooms": len(rooms),
        "faculty": len(faculty),
        "subjects": len(subjects),
        "sections": len(sections),
        "section_subjects": len(section_subjects),
        "schedule": len(schedule),
    }


def delete_schedule():
    """Remove every scheduled class block; nothing else is touched."""
    with closing(connect()) as db:
        try:
            db.execute("BEGIN")
            db.execute("DELETE FROM schedules")
            db.commit()
        except Exception:
            db.rollback()
            raise
