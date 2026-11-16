"""SQLite-backed scheduling data and domain operations."""

import sqlite3
from contextlib import closing

from flask import current_app


def connect():
    connection = sqlite3.connect(current_app.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with closing(connect()) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS faculty (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'Active',
                weekly_capacity INTEGER NOT NULL DEFAULT 40
            );
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                units INTEGER NOT NULL CHECK (units IN (2, 3, 5)),
                room_type TEXT NOT NULL CHECK (room_type IN ('Lecture', 'Laboratory', 'Both')),
                faculty_id INTEGER NOT NULL REFERENCES faculty(id),
                room_id INTEGER REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL CHECK (type IN ('Lecture', 'Laboratory')),
                seats INTEGER NOT NULL DEFAULT 40
            );
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                year INTEGER NOT NULL CHECK (year BETWEEN 1 AND 4),
                program TEXT NOT NULL CHECK (program IN ('BSCS', 'BSIT'))
            );
            CREATE TABLE IF NOT EXISTS section_subjects (
                section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                PRIMARY KEY (section_id, subject_id)
            );
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY,
                subject_id INTEGER NOT NULL REFERENCES subjects(id),
                section_id INTEGER NOT NULL REFERENCES sections(id),
                faculty_id INTEGER NOT NULL REFERENCES faculty(id),
                room_id INTEGER NOT NULL REFERENCES rooms(id),
                day TEXT NOT NULL,
                start INTEGER NOT NULL,
                end INTEGER NOT NULL,
                session_type TEXT NOT NULL DEFAULT 'Lecture',
                status TEXT NOT NULL DEFAULT 'approved',
                CHECK (start >= 7 AND end <= 18 AND end > start)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                role TEXT NOT NULL CHECK (role IN ('dean')),
                password_hash TEXT NOT NULL
            );
            """
        )
        subject_columns = {row["name"] for row in db.execute("PRAGMA table_info(subjects)")}
        if "delivery" not in subject_columns:
            db.execute(
                "ALTER TABLE subjects ADD COLUMN delivery TEXT NOT NULL DEFAULT 'In-person'"
            )
        if "room_id" not in subject_columns:
            db.execute("ALTER TABLE subjects ADD COLUMN room_id INTEGER REFERENCES rooms(id)")
        # Seed starter data only once per database. Deleting everything (or a
        # restore) must never trigger a silent re-seed on the next restart.
        meta = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        already_seeded = bool(
            meta and db.execute("SELECT 1 FROM meta WHERE key = 'seeded'").fetchone()
        )
        if not already_seeded:
            _seed_database(db)
        db.execute(
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('seeded', '1')")
        db.commit()


def _seed_database(db):
    # Only populate a completely fresh database. Re-running must never bring back
    # starter records that the user has deleted.
    if db.execute("SELECT COUNT(*) FROM faculty").fetchone()[0]:
        return
    faculty = [
        "Rolan Sotomayor", "Mia Reyes", "Daniel Santos", "Angela Cruz",
        "Paolo Garcia", "Lena Mendoza",
    ]
    db.executemany("INSERT OR IGNORE INTO faculty(name) VALUES (?)", [(name,) for name in faculty])
    rooms = [
        ("Room 103", "Lecture", 40), ("Room 104", "Lecture", 40),
        ("Room 105", "Lecture", 40), ("Room 106", "Lecture", 40),
        ("CCS Quadrangle", "Lecture", 40), ("Room 202", "Lecture", 40),
        ("Lab 203", "Laboratory", 38), ("Lab 204", "Laboratory", 38),
        ("Lab 205", "Laboratory", 38), ("Lab 206", "Laboratory", 38),
        ("Mac Lab", "Lecture", 38), ("Room 208", "Lecture", 40),
        ("TESOL", "Lecture", 36),
    ]
    db.executemany(
        "INSERT OR IGNORE INTO rooms(name, type, seats) VALUES (?, ?, ?)", rooms
    )
    db.execute(
        "INSERT OR IGNORE INTO rooms(name, type, seats) VALUES ('Online', 'Lecture', 9999)"
    )
    subject_rows = []
    section_rows = []
    links = []
    faculty_ids = [row[0] for row in db.execute("SELECT id FROM faculty ORDER BY id")]
    faculty_index = 0
    for program in ("BSCS", "BSIT"):
        for year in range(1, 5):
            section_name = f"{program} {year}A"
            section_rows.append((section_name, year, program))
            first_code = "CMSC" if program == "BSCS" else "ITEC"
            for subject_index, (suffix, title, units, room_type) in enumerate(
                (("01", "Computing Fundamentals", 3, "Lecture"),
                 ("02", "Programming Laboratory", 5, "Both"),
                 ("03", "Information Systems", 2, "Lecture"))
            ):
                code = f"{first_code} {year}{suffix}"
                subject_rows.append(
                    (code, f"Year {year} {title}", units, room_type, faculty_ids[faculty_index % len(faculty_ids)])
                )
                faculty_index += 1
    db.executemany(
        "INSERT OR IGNORE INTO sections(name, year, program) VALUES (?, ?, ?)", section_rows
    )
    db.executemany(
        "INSERT OR IGNORE INTO subjects(code, title, units, room_type, faculty_id) VALUES (?, ?, ?, ?, ?)",
        subject_rows,
    )
    section_ids = {row["name"]: row["id"] for row in db.execute("SELECT id, name FROM sections")}
    subject_ids = {row["code"]: row["id"] for row in db.execute("SELECT id, code FROM subjects")}
    for program in ("BSCS", "BSIT"):
        prefix = "CMSC" if program == "BSCS" else "ITEC"
        for year in range(1, 5):
            for suffix in ("01", "02", "03"):
                links.append((section_ids[f"{program} {year}A"], subject_ids[f"{prefix} {year}{suffix}"]))
    db.executemany(
        "INSERT OR IGNORE INTO section_subjects(section_id, subject_id) VALUES (?, ?)", links
    )
    if db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0] == 0:
        first_subject = db.execute(
            "SELECT s.id, s.faculty_id, se.id, r.id FROM subjects s "
            "JOIN section_subjects ss ON ss.subject_id = s.id "
            "JOIN sections se ON se.id = ss.section_id "
            "JOIN rooms r ON r.type = 'Lecture' "
            "WHERE s.code = 'CMSC 301' AND se.name = 'BSCS 3A' ORDER BY r.id LIMIT 1"
        ).fetchone()
        if first_subject:
            db.execute(
                "INSERT INTO schedules(subject_id, faculty_id, section_id, room_id, day, start, end, session_type) "
                "VALUES (?, ?, ?, ?, 'THU', 11, 14, 'Lecture')",
                tuple(first_subject),
            )


def get_faculty():
    with closing(connect()) as db:
        faculty = db.execute(
            "SELECT id, name, status, weekly_capacity FROM faculty ORDER BY name"
        ).fetchall()
        result = []
        for item in faculty:
            subjects = db.execute(
                "SELECT s.id, s.code, s.title, s.units, s.room_type, s.delivery, s.room_id, "
                "r.name AS fixed_room FROM subjects s LEFT JOIN rooms r ON r.id = s.room_id "
                "WHERE s.faculty_id = ? ORDER BY s.code", (item["id"],)
            ).fetchall()
            weekly_hours = sum(subject["units"] for subject in subjects)
            result.append(
                {
                    **dict(item),
                    "courses": ", ".join(row["code"] for row in subjects) or "No subjects assigned",
                    "subjects": [dict(row) for row in subjects],
                    "weekly_hours": weekly_hours,
                }
            )
        return result


def add_faculty(name):
    name = name.strip()
    if not name:
        raise ValueError("Enter a faculty member's name.")
    with closing(connect()) as db:
        try:
            cursor = db.execute("INSERT INTO faculty(name) VALUES (?)", (name,))
            db.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise ValueError("That faculty member already exists.") from error


def remove_faculty(faculty_id):
    try:
        faculty_id = int(faculty_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Choose a valid faculty member.") from error
    with closing(connect()) as db:
        faculty = db.execute("SELECT id FROM faculty WHERE id = ?", (faculty_id,)).fetchone()
        if not faculty:
            raise ValueError("Faculty member not found.")
        subject_ids = [row["id"] for row in db.execute(
            "SELECT id FROM subjects WHERE faculty_id = ?", (faculty_id,)
        )]
        if subject_ids:
            placeholders = ",".join("?" for _ in subject_ids)
            db.execute(f"DELETE FROM schedules WHERE subject_id IN ({placeholders})", subject_ids)
            db.execute(f"DELETE FROM section_subjects WHERE subject_id IN ({placeholders})", subject_ids)
            db.execute(f"DELETE FROM subjects WHERE id IN ({placeholders})", subject_ids)
        db.execute("DELETE FROM schedules WHERE faculty_id = ?", (faculty_id,))
        db.execute("DELETE FROM faculty WHERE id = ?", (faculty_id,))
        db.commit()
        return len(subject_ids)


def _fixed_room_id(db, room_id, room_type, delivery):
    """Validate a subject's fixed room. None or blank means any matching room."""
    if room_id in (None, ""):
        return None
    if delivery == "Online":
        raise ValueError("Online subjects cannot be fixed to a physical room.")
    if room_type == "Both":
        raise ValueError(
            "A subject that uses both lecture and laboratory rooms cannot be fixed to one room."
        )
    try:
        room_id = int(room_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Choose a valid fixed room.") from error
    room = db.execute(
        "SELECT id, name, type FROM rooms WHERE id = ? AND lower(name) != 'online'",
        (room_id,),
    ).fetchone()
    if not room:
        raise ValueError("Choose an existing physical room.")
    if room_type != "Both" and room["type"] != room_type:
        raise ValueError(
            f"A {room_type.lower()} subject needs a {room_type.lower()} room; "
            f"{room['name']} is a {room['type'].lower()} room."
        )
    return room["id"]


def add_subject(faculty_id, code, title, units, room_type, delivery="In-person", room_id=None):
    code = code.strip().upper()
    title = title.strip()
    try:
        faculty_id = int(faculty_id)
        units = int(units)
    except (TypeError, ValueError) as error:
        raise ValueError("Choose a faculty member and valid unit count.") from error
    if not code or not title or units not in (2, 3, 5):
        raise ValueError("Enter a subject code, title, and 2, 3, or 5 units.")
    if room_type not in ("Lecture", "Laboratory", "Both"):
        raise ValueError("Choose Lecture, Laboratory, or Both for the room type.")
    if delivery not in ("In-person", "Online"):
        raise ValueError("Choose In-person or Online delivery.")
    with closing(connect()) as db:
        room_id = _fixed_room_id(db, room_id, room_type, delivery)
        try:
            cursor = db.execute(
                "INSERT INTO subjects(code, title, units, room_type, faculty_id, delivery, room_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, title, units, room_type, faculty_id, delivery, room_id),
            )
            db.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise ValueError("Subject code already exists or faculty member is invalid.") from error


def update_subject(subject_id, faculty_id, code, title, units, room_type, delivery, room_id=None):
    code = code.strip().upper()
    title = title.strip()
    try:
        subject_id = int(subject_id)
        faculty_id = int(faculty_id)
        units = int(units)
    except (TypeError, ValueError) as error:
        raise ValueError("Choose a faculty member and valid unit count.") from error
    if not code or not title or units not in (2, 3, 5):
        raise ValueError("Enter a subject code, title, and 2, 3, or 5 units.")
    if room_type not in ("Lecture", "Laboratory", "Both"):
        raise ValueError("Choose Lecture, Laboratory, or Both for the room type.")
    if delivery not in ("In-person", "Online"):
        raise ValueError("Choose In-person or Online delivery.")
    with closing(connect()) as db:
        subject = db.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        if not subject:
            raise ValueError("Subject not found.")
        room_id = _fixed_room_id(db, room_id, room_type, delivery)
        try:
            db.execute(
                "UPDATE subjects SET faculty_id = ?, code = ?, title = ?, units = ?, room_type = ?, "
                "delivery = ?, room_id = ? WHERE id = ?",
                (faculty_id, code, title, units, room_type, delivery, room_id, subject_id),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Subject code already exists or faculty member is invalid.") from error
        needs_reschedule = any(
            subject[key] != value
            for key, value in (("faculty_id", faculty_id), ("units", units),
                               ("room_type", room_type), ("delivery", delivery),
                               ("room_id", room_id))
        )
        removed_blocks = 0
        if needs_reschedule:
            removed_blocks = db.execute(
                "DELETE FROM schedules WHERE subject_id = ?", (subject_id,)
            ).rowcount
        db.commit()
        return removed_blocks


def remove_subject(subject_id):
    try:
        subject_id = int(subject_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Choose a valid subject.") from error
    with closing(connect()) as db:
        subject = db.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        if not subject:
            raise ValueError("Subject not found.")
        removed_blocks = db.execute(
            "DELETE FROM schedules WHERE subject_id = ?", (subject_id,)
        ).rowcount
        db.execute("DELETE FROM section_subjects WHERE subject_id = ?", (subject_id,))
        db.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
        db.commit()
        return removed_blocks


def add_room(name, room_type, seats):
    name = name.strip()
    if not name or name.casefold() == "online" or room_type not in ("Lecture", "Laboratory"):
        raise ValueError("Enter a room name and select Lecture or Laboratory.")
    try:
        seats = int(seats)
    except (TypeError, ValueError) as error:
        raise ValueError("Room capacity must be a positive number.") from error
    if seats < 1:
        raise ValueError("Room capacity must be a positive number.")
    with closing(connect()) as db:
        try:
            cursor = db.execute(
                "INSERT INTO rooms(name, type, seats) VALUES (?, ?, ?)",
                (name, room_type, seats),
            )
            db.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise ValueError("That room already exists.") from error


def add_section(name, year, program):
    name = " ".join(name.strip().split()).upper()
    try:
        year = int(year)
    except (TypeError, ValueError) as error:
        raise ValueError("Year must be 1, 2, 3, or 4.") from error
    if not name or len(name) > 40:
        raise ValueError("Enter a section name (max 40 characters), e.g. 'BSCS 1C'.")
    if year not in (1, 2, 3, 4):
        raise ValueError("Year must be 1, 2, 3, or 4.")
    program = (program or "").strip().upper()
    if program not in ("BSCS", "BSIT"):
        raise ValueError("Program must be BSCS or BSIT.")
    with closing(connect()) as db:
        try:
            cursor = db.execute(
                "INSERT INTO sections(name, year, program) VALUES (?, ?, ?)",
                (name, year, program),
            )
            db.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise ValueError("That section already exists.") from error


def get_rooms(include_online=False):
    with closing(connect()) as db:
        query = "SELECT * FROM rooms"
        if not include_online:
            query += " WHERE lower(name) != 'online'"
        return [dict(row) for row in db.execute(query + " ORDER BY type, name")]


def get_subjects():
    with closing(connect()) as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT s.*, f.name AS faculty_name, r.name AS fixed_room FROM subjects s "
                "JOIN faculty f ON f.id = s.faculty_id "
                "LEFT JOIN rooms r ON r.id = s.room_id ORDER BY s.code"
            )
        ]


def get_sections():
    with closing(connect()) as db:
        sections = db.execute("SELECT * FROM sections ORDER BY year, program, name").fetchall()
        result = []
        for section in sections:
            subjects = db.execute(
                "SELECT s.id, s.code, s.title, s.units, s.room_type, s.delivery, s.room_id, "
                "r.name AS fixed_room, f.name AS faculty_name "
                "FROM section_subjects ss JOIN subjects s ON s.id = ss.subject_id "
                "JOIN faculty f ON f.id = s.faculty_id "
                "LEFT JOIN rooms r ON r.id = s.room_id "
                "WHERE ss.section_id = ? ORDER BY s.code",
                (section["id"],),
            ).fetchall()
            result.append({**dict(section), "subjects": [dict(subject) for subject in subjects]})
        return result


def add_subject_to_section(section_id, subject_id):
    with closing(connect()) as db:
        try:
            db.execute(
                "INSERT INTO section_subjects(section_id, subject_id) VALUES (?, ?)",
                (int(section_id), int(subject_id)),
            )
            db.commit()
        except (ValueError, sqlite3.IntegrityError) as error:
            raise ValueError("Choose a valid section and subject; duplicates are not allowed.") from error


def _schedule_rows(db):
    return db.execute(
        "SELECT sc.*, s.code AS course, s.title AS subject_title, s.units, s.room_type AS subject_room_type, "
        "s.delivery, se.name AS section, f.name AS instructor, r.name AS room, r.type AS room_type "
        "FROM schedules sc JOIN subjects s ON s.id = sc.subject_id "
        "JOIN sections se ON se.id = sc.section_id "
        "JOIN faculty f ON f.id = sc.faculty_id JOIN rooms r ON r.id = sc.room_id "
        "ORDER BY sc.day, sc.start, se.name, s.code"
    ).fetchall()


# NSTP blocks are shown on Sundays for first-year sections (including BSIT 1C).
NSTP_EXCLUDED_SECTIONS = ()
NSTP_INCLUDED_SECTIONS = ()


def _nstp_sections(db):
    where = "year = 1"
    if NSTP_EXCLUDED_SECTIONS:
        placeholders = ", ".join("?" for _ in NSTP_EXCLUDED_SECTIONS)
        where += f" AND name NOT IN ({placeholders})"
    sql = f"SELECT id, name FROM sections WHERE {where}"
    if NSTP_INCLUDED_SECTIONS:
        placeholders = ", ".join("?" for _ in NSTP_INCLUDED_SECTIONS)
        sql += f" OR name IN ({placeholders})"
    sql += " ORDER BY program, name"
    return db.execute(sql, (*NSTP_EXCLUDED_SECTIONS, *NSTP_INCLUDED_SECTIONS)).fetchall()


def _surname(name):
    parts = (name or "").strip().split()
    return parts[-1] if parts else ""


def get_instructor_surnames():
    """Distinct faculty surnames, for the master-schedule instructor filter."""
    with closing(connect()) as db:
        names = [row[0] for row in db.execute("SELECT name FROM faculty")]
    return sorted({_surname(name) for name in names if _surname(name)}, key=str.casefold)


def get_schedules(instructor=None, section=None, room=None):
    with closing(connect()) as db:
        result = []
        for row in _schedule_rows(db):
            item = dict(row)
            if item["delivery"] == "Online":
                item["room"] = "Online"
                item["room_type"] = "Online"
            item["slot"] = f"{item['day']} {format_time(item['start'])} - {format_time(item['end'])}"
            result.append(item)
        first_year_sections = _nstp_sections(db)
        for nstp_section in first_year_sections:
            item = {
                "id": None,
                "subject_id": None,
                "section_id": nstp_section["id"],
                "faculty_id": None,
                "room_id": None,
                "day": "SUN",
                "start": 7,
                "end": 17,
                "session_type": "NSTP",
                "status": "approved",
                "course": "NSTP",
                "subject_title": "National Service Training Program",
                "units": 0,
                "subject_room_type": "",
                "delivery": "In-person",
                "section": nstp_section["name"],
                "instructor": "",
                "room": "",
                "room_type": "",
                "is_nstp": True,
            }
            item["slot"] = "SUN 7:00AM - 5:00PM"
            result.append(item)
        day_order = {day: index for index, day in enumerate(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"))}
        # Conflicts first so they are easy to spot, then the rest by day/time.
        result.sort(key=lambda item: (item["status"] != "conflict", day_order[item["day"]], item["start"], item["section"], item["course"]))
        if instructor:
            # Only the selected professor's classes; NSTP blocks have no instructor.
            result = [
                item for item in result
                if not item.get("is_nstp") and _surname(item["instructor"]) == instructor
            ]
        if section:
            # Only the selected section's classes, including its NSTP block.
            result = [item for item in result if item["section"] == section]
        if room:
            # Only classes scheduled in the selected room; NSTP blocks have no room.
            result = [item for item in result if not item.get("is_nstp") and item["room"] == room]
        return result


def get_weekly_schedule(section_id=None, room_id=None, instructor=None, section=None, room=None):
    schedules = get_schedules(instructor, section=section, room=room)
    if section_id is not None:
        schedules = [item for item in schedules if item["section_id"] == int(section_id)]
    if room_id is not None:
        schedules = [
            item for item in schedules
            if not item.get("is_nstp") and item["room_id"] == int(room_id)
        ]
    days = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    columns = []
    for day in days:
        events = [item for item in schedules if item["day"] == day]
        events.sort(key=lambda item: (item["start"], item["end"], item["section"], item["course"]))
        lane_ends = []
        for event in events:
            event_end = min(event["end"], 17)
            lane = next(
                (index for index, lane_end in enumerate(lane_ends) if lane_end <= event["start"]),
                len(lane_ends),
            )
            if lane == len(lane_ends):
                lane_ends.append(event_end)
            else:
                lane_ends[lane] = event_end
            event["lane"] = lane
            event["grid_start"] = int((event["start"] - 7) * 2 + 1)
            event["grid_end"] = int((event_end - 7) * 2 + 1)
        columns.append({"day": day, "events": events, "lane_count": max(1, len(lane_ends))})
    return {
        "days": columns,
        "times": [
            {"hour": hour, "minute": minute, "label": _slot_label(hour, minute)}
            for hour in range(7, 17)
            for minute in (0, 30)
        ],
    }


def _time_label(hour, minute):
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour if hour <= 12 else hour - 12
    return f"{hour12}:{minute:02d} {suffix}"


def _slot_label(hour, minute):
    end_hour, end_minute = (hour + 1, 0) if minute == 30 else (hour, 30)
    return f"{_time_label(hour, minute)} - {_time_label(end_hour, end_minute)}"


def format_time(hour):
    hour = float(hour)
    minute = 30 if hour % 1 else 0
    whole = int(hour)
    return f"{whole if whole <= 12 else whole - 12}:{minute:02d}{'AM' if whole < 12 else 'PM'}"


def time_options():
    """Start/end dropdown options in 30-minute increments (7:00 AM - 5:00 PM)."""
    start_options = []
    end_options = []
    for hour in range(7, 17):
        for minute in (0, 30):
            value = float(hour) + minute / 60
            label = f"{hour if hour <= 12 else hour - 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
            start_options.append((value, label))
    for hour in range(7, 17):
        for minute in (0, 30):
            value = float(hour) + minute / 60
            label = f"{hour if hour <= 12 else hour - 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
            if value >= 7.5:
                end_options.append((value, label))
    value = 17.0
    end_options.append((value, "5:00 PM"))
    return {"start_options": start_options, "end_options": end_options}


def get_stats(instructor=None, section=None, room=None):
    if instructor or section or room:
        rows = get_schedules(instructor, section=section, room=room)
        classes = len(rows)
        conflicts = sum(1 for item in rows if item["status"] == "conflict")
        return {"classes": classes, "approved": classes, "conflicts": conflicts, "pending": 0}
    with closing(connect()) as db:
        classes = db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
        conflicts = db.execute("SELECT COUNT(*) FROM schedules WHERE status = 'conflict'").fetchone()[0]
        return {"classes": classes, "approved": classes, "conflicts": conflicts, "pending": 0}


def _get_schedule_context(db, schedule_id=None):
    if schedule_id is not None:
        existing = db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if not existing:
            raise ValueError("Schedule entry not found.")
        return dict(existing)
    return {}


def find_conflicts(day, start, end, room_id, faculty_id, section_id, exclude_id=None, scheduled=None, is_online=False):
    start, end = float(start), float(end)
    if day not in ("MON", "TUE", "WED", "THU", "FRI", "SAT") or start < 7 or end > 17 or end <= start:
        return ["Choose a valid weekday and a time between 7 AM and 5 PM."]
    conflicts = []
    if scheduled is None:
        with closing(connect()) as db:
            rows = db.execute(
                "SELECT sc.*, s.code, s.delivery, se.name AS section_name, f.name AS faculty_name, r.name AS room_name "
                "FROM schedules sc JOIN subjects s ON s.id = sc.subject_id "
                "JOIN sections se ON se.id = sc.section_id JOIN faculty f ON f.id = sc.faculty_id "
                "JOIN rooms r ON r.id = sc.room_id WHERE sc.day = ? AND sc.start < ? AND sc.end > ?",
                (day, end, start),
            ).fetchall()
    else:
        rows = scheduled
    for row in rows:
        if exclude_id is not None and row["id"] == int(exclude_id):
            continue
        if not is_online and row["delivery"] != "Online" and row["room_id"] == int(room_id):
            conflicts.append(f"{row['room_name'] if 'room_name' in row.keys() else 'Room'} is already booked for {row['code']}.")
        if row["faculty_id"] == int(faculty_id):
            conflicts.append(f"Faculty member is already teaching {row['code']} ({row['section_name'] if 'section_name' in row.keys() else 'another section'}).")
        if row["section_id"] == int(section_id):
            conflicts.append(f"Section is already taking {row['code']} at this time.")
    return conflicts


def save_schedule(subject_id, section_id, room_id, day, start, end, session_type=None, schedule_id=None):
    with closing(connect()) as db:
        subject = db.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        section = db.execute("SELECT id FROM sections WHERE id = ?", (section_id,)).fetchone()
        if subject and subject["delivery"] == "Online":
            room = db.execute("SELECT * FROM rooms WHERE name = 'Online'").fetchone()
            room_id = room["id"] if room else None
        else:
            room = db.execute("SELECT * FROM rooms WHERE id = ? AND name != 'Online'", (room_id,)).fetchone()
        if not subject or not section or not room:
            raise ValueError("Choose an existing subject, section, and room.")
        if not db.execute(
            "SELECT 1 FROM section_subjects WHERE section_id = ? AND subject_id = ?",
            (section_id, subject_id),
        ).fetchone():
            raise ValueError("This subject is not assigned to the selected section.")
        expected = subject["room_type"]
        is_online = subject["delivery"] == "Online"
        if not is_online and expected != "Both" and room["type"] != expected:
            raise ValueError(f"This subject requires a {expected.lower()} room.")
        if not is_online and expected == "Both" and room["type"] not in ("Lecture", "Laboratory"):
            raise ValueError("This subject requires a lecture or laboratory room.")
        if not is_online and subject["room_id"] and int(subject["room_id"]) != int(room_id):
            fixed = db.execute(
                "SELECT name FROM rooms WHERE id = ?", (subject["room_id"],)
            ).fetchone()
            raise ValueError(
                f"{subject['code']} must be scheduled in {fixed['name'] if fixed else 'its fixed room'}."
            )
        conflicts = find_conflicts(
            day, start, end, room_id, subject["faculty_id"], section_id, schedule_id,
            is_online=is_online,
        )
        if conflicts:
            raise ValueError("Schedule conflict: " + " ".join(conflicts))
        values = (
            subject_id, section_id, subject["faculty_id"], room_id, day,
            float(start), float(end), "Online" if is_online else session_type or room["type"],
        )
        if schedule_id is None:
            cursor = db.execute(
                "INSERT INTO schedules(subject_id, section_id, faculty_id, room_id, day, start, end, session_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values
            )
            entry_id = cursor.lastrowid
        else:
            _get_schedule_context(db, schedule_id)
            db.execute(
                "UPDATE schedules SET subject_id = ?, section_id = ?, faculty_id = ?, room_id = ?, day = ?, start = ?, end = ?, session_type = ? WHERE id = ?",
                (*values, schedule_id),
            )
            entry_id = int(schedule_id)
        db.commit()
        return entry_id


def _build_jobs(subjects):
    jobs = []
    for subject in subjects:
        if subject["delivery"] == "Online":
            sessions = (("Online", 3), ("Online", 2)) if subject["units"] == 5 else (("Online", subject["units"]),)
        elif subject["room_type"] == "Both":
            sessions = {
                2: (("Lecture", 1), ("Laboratory", 1)),
                3: (("Lecture", 1), ("Laboratory", 2)),
                5: (("Lecture", 2), ("Laboratory", 3)),
            }[subject["units"]]
        elif subject["units"] == 5:
            sessions = ((subject["room_type"], 3), (subject["room_type"], 2))
        else:
            sessions = ((subject["room_type"], subject["units"]),)
        for session_type, duration in sessions:
            jobs.append({**dict(subject), "session_type": session_type, "duration": duration})
    return jobs


def _preflight_check(db):
    """Fail fast with an actionable message when the data cannot fit the rules."""
    days = 6  # MON..SAT
    max_section_hours = 5 * days
    faculty_week_hours = 60  # 6 days x 10 hours (07:00-17:00)

    section_overload = [
        f"{row['name']} ({row['hours']}h)"
        for row in db.execute(
            "SELECT se.name, SUM(CASE WHEN s.delivery != 'Online' THEN s.units ELSE 0 END) AS hours "
            "FROM section_subjects ss JOIN subjects s ON s.id = ss.subject_id "
            "JOIN sections se ON se.id = ss.section_id GROUP BY se.id HAVING hours > ?",
            (max_section_hours,),
        )
    ]
    faculty_overload = [
        f"{row['name']} ({row['hours']}h)"
        for row in db.execute(
            "SELECT f.name, SUM(CASE WHEN s.delivery != 'Online' THEN s.units ELSE 0 END) AS hours "
            "FROM section_subjects ss JOIN subjects s ON s.id = ss.subject_id "
            "JOIN faculty f ON f.id = s.faculty_id GROUP BY f.id HAVING hours > ?",
            (faculty_week_hours,),
        )
    ]
    problems = []
    if section_overload:
        problems.append(
            "Section(s) over the 30h/week limit (5h/day, Mon-Sat): "
            + ", ".join(sorted(section_overload))
            + ". Make some of their subjects Online, reduce units, or remove assignments."
        )
    if faculty_overload:
        problems.append(
            "Faculty over the 60h/week available (Mon-Sat, 07:00-17:00): "
            + ", ".join(sorted(faculty_overload))
            + ". Reassign some of their subjects to other faculty members."
        )
    if problems:
        raise ValueError("Cannot generate the schedule yet. " + " ".join(problems))


def _min_conflicts_repair(jobs, days, rooms, online_room_id, max_steps=40000, time_budget=25.0, seed=0):
    """Best-effort repair solver (pure Python).

    Assigns every job greedily into its least-conflicting slot, then climbs to
    zero conflicts. Returns the placed list when it reaches a clean assignment,
    otherwise None.
    """
    import random
    import time
    from collections import defaultdict

    day_index = {day: index for index, day in enumerate(days)}
    slots = [(d, s) for d in day_index for s in range(7, 17)]

    def job_room_ids(job):
        if job["session_type"] == "Online":
            return [online_room_id]
        if job.get("room_id"):
            return [
                room["id"]
                for room in rooms
                if room["id"] == job["room_id"] and room["type"] == job["session_type"]
            ]
        return [room["id"] for room in rooms if room["type"] == job["session_type"] and room["name"] != "Online"]

    domains = []
    for job in jobs:
        domain = [
            (d, s, room_id)
            for d, s in slots
            if s + job["duration"] <= 17
            for room_id in job_room_ids(job)
        ]
        if not domain:
            return None
        domains.append(domain)

    total = len(jobs)
    rng = random.Random(seed)
    assignment = [None] * total
    faculty_occ = defaultdict(list)
    section_occ = defaultdict(list)
    room_occ = defaultdict(list)
    section_day_hours = defaultdict(int)
    section_day_count = defaultdict(int)
    subject_section_day = defaultdict(int)

    def is_online(job):
        return job["session_type"] == "Online"

    def add(index, slot):
        job = jobs[index]
        day, start, room_id = slot
        end = start + job["duration"]
        faculty_occ[(job["faculty_id"], day)].append((start, end, index))
        section_occ[(job["section_id"], day)].append((start, end, index))
        if not is_online(job):
            room_occ[(room_id, day)].append((start, end, index))
            section_day_hours[(job["section_id"], day)] += job["duration"]
            section_day_count[(job["section_id"], day)] += 1
        subject_section_day[(job["section_id"], job["subject_id"], day)] += 1

    def remove(index):
        job = jobs[index]
        day, start, room_id = assignment[index]
        end = start + job["duration"]
        faculty_occ[(job["faculty_id"], day)].remove((start, end, index))
        section_occ[(job["section_id"], day)].remove((start, end, index))
        if not is_online(job):
            room_occ[(room_id, day)].remove((start, end, index))
            section_day_hours[(job["section_id"], day)] -= job["duration"]
            section_day_count[(job["section_id"], day)] -= 1
        subject_section_day[(job["section_id"], job["subject_id"], day)] -= 1

    def overlap(a_start, a_end, b_start, b_end):
        return a_start < b_end and b_start < a_end

    def slot_conflict_count(index, day, start, room_id):
        """Conflicts job would have if placed at the candidate slot (job absent from occupancy)."""
        job = jobs[index]
        end = start + job["duration"]
        conflicts = 0
        for other_start, other_end, _ in faculty_occ[(job["faculty_id"], day)]:
            if overlap(start, end, other_start, other_end):
                conflicts += 1
        for other_start, other_end, _ in section_occ[(job["section_id"], day)]:
            if not (other_end + 1 <= start or end + 1 <= other_start):
                conflicts += 1
        if not is_online(job):
            for other_start, other_end, _ in room_occ[(room_id, day)]:
                if overlap(start, end, other_start, other_end):
                    conflicts += 1
            hours = section_day_hours[(job["section_id"], day)]
            count = section_day_count[(job["section_id"], day)]
            if hours + job["duration"] > 5:
                conflicts += (hours + job["duration"]) - 5
            if count + 1 > 2:
                conflicts += (count + 1) - 2
        if subject_section_day[(job["section_id"], job["subject_id"], day)] > 0:
            conflicts += subject_section_day[(job["section_id"], job["subject_id"], day)]
        return conflicts

    # Greedy construction: most constrained jobs first, least-conflicting slot
    order = sorted(range(total), key=lambda index: len(domains[index]))
    for index in order:
        best_slot = min(
            domains[index],
            key=lambda slot: slot_conflict_count(index, *slot),
        )
        assignment[index] = best_slot
        add(index, best_slot)

    def conflicts_of(index):
        job = jobs[index]
        day, start, room_id = assignment[index]
        end = start + job["duration"]
        conflicts = 0
        for other_start, other_end, other in faculty_occ[(job["faculty_id"], day)]:
            if other != index and overlap(start, end, other_start, other_end):
                conflicts += 1
        for other_start, other_end, other in section_occ[(job["section_id"], day)]:
            if other != index and not (other_end + 1 <= start or end + 1 <= other_start):
                conflicts += 1
        if not is_online(job):
            for other_start, other_end, other in room_occ[(room_id, day)]:
                if other != index and overlap(start, end, other_start, other_end):
                    conflicts += 1
            if section_day_hours[(job["section_id"], day)] > 5:
                conflicts += section_day_hours[(job["section_id"], day)] - 5
            if section_day_count[(job["section_id"], day)] > 2:
                conflicts += section_day_count[(job["section_id"], day)] - 2
        duplicates = subject_section_day[(job["section_id"], job["subject_id"], day)]
        if duplicates > 1:
            conflicts += duplicates - 1
        return conflicts

    started = time.time()
    for step in range(max_steps):
        conflicted = [index for index in range(total) if conflicts_of(index)]
        if not conflicted:
            placed = []
            for index, job in enumerate(jobs):
                day, start, room_id = assignment[index]
                placed.append({**job, "room_id": room_id, "day": day, "start": start, "end": start + job["duration"]})
            placed.sort(key=lambda item: (days.index(item["day"]), item["start"], item["section_id"]))
            return placed
        if time.time() - started > time_budget:
            return None
        target = rng.choice(conflicted)
        remove(target)
        options = [
            (slot, slot_conflict_count(target, *slot))
            for slot in domains[target]
        ]
        best = min(conflicts for _, conflicts in options)
        assignment[target] = rng.choice([slot for slot, conflicts in options if conflicts == best])
        add(target, assignment[target])
    return None


def _place_jobs(jobs, days, starts, rooms, online_room_id, seed):
    """Single placement attempt. Returns (placed, failed_job)."""
    import random

    rng = random.Random(seed)
    # In-person sessions first (they fight over rooms and daily caps);
    # Online sessions last since they only need a faculty/section slot.
    ordered = sorted(
        jobs,
        key=lambda job: (job["session_type"] == "Online", -job["duration"], rng.random()),
    )
    placed = []
    section_day_hours = {}
    section_day_count = {}

    def is_online(job):
        return job["session_type"] == "Online"

    for job in ordered:
        placed_job = None
        candidate_days = list(days)
        rng.shuffle(candidate_days)
        candidate_days.sort(
            key=lambda day: (
                section_day_hours.get((job["section_id"], day), 0),
                section_day_count.get((job["section_id"], day), 0),
                days.index(day),
            ),
        )
        for day in candidate_days:
            if any(
                prior["subject_id"] == job["subject_id"]
                and prior["section_id"] == job["section_id"]
                and prior["day"] == day
                for prior in placed
            ):
                continue
            if not is_online(job):
                if section_day_count.get((job["section_id"], day), 0) >= 2:
                    continue
                if section_day_hours.get((job["section_id"], day), 0) + job["duration"] > 5:
                    continue
            for start in starts:
                end = start + job["duration"]
                if end > 17:
                    continue
                if is_online(job):
                    candidate_rooms = [{"id": online_room_id, "type": "Online"}]
                elif job.get("room_id"):
                    candidate_rooms = [
                        room for room in rooms
                        if room["id"] == job["room_id"] and room["type"] == job["session_type"]
                    ]
                else:
                    candidate_rooms = [
                        room for room in rooms
                        if room["type"] == job["session_type"] and room["name"] != "Online"
                    ]
                rng.shuffle(candidate_rooms)
                for room in candidate_rooms:
                    if room["type"] != job["session_type"]:
                        continue
                    conflict = any(
                        prior["day"] == day
                        and (
                            (prior["faculty_id"] == job["faculty_id"]
                             and prior["start"] < end and prior["end"] > start)
                            or (not is_online(job)
                                and prior["session_type"] != "Online"
                                and prior["room_id"] == room["id"]
                                and prior["start"] < end and prior["end"] > start)
                            or (prior["section_id"] == job["section_id"]
                                and not (prior["end"] + 1 <= start or end + 1 <= prior["start"]))
                        )
                        for prior in placed
                    )
                    if not conflict:
                        placed_job = {
                            **job, "room_id": room["id"], "day": day,
                            "start": start, "end": end,
                        }
                        break
                if placed_job:
                    break
            if placed_job:
                break
        if not placed_job:
            return None, job
        placed.append(placed_job)
        if not is_online(placed_job):
            key = (job["section_id"], placed_job["day"])
            section_day_hours[key] = section_day_hours.get(key, 0) + job["duration"]
            section_day_count[key] = section_day_count.get(key, 0) + 1
    return placed, None


def generate_schedule():
    days = ("MON", "TUE", "WED", "THU", "FRI", "SAT")
    starts = tuple(range(7, 17))
    with closing(connect()) as db:
        subjects = db.execute(
            "SELECT ss.section_id, s.id AS subject_id, s.faculty_id, s.code, s.units, s.room_type, s.delivery, s.room_id "
            "FROM section_subjects ss JOIN subjects s ON s.id = ss.subject_id "
            "ORDER BY ss.section_id, s.units DESC, s.code"
        ).fetchall()
        rooms = [dict(room) for room in db.execute("SELECT * FROM rooms ORDER BY seats DESC, id")]
        online_room = db.execute("SELECT id FROM rooms WHERE name = 'Online'").fetchone()
        if not subjects or not rooms or not online_room:
            raise ValueError("Add subjects, sections, and rooms before generating a schedule.")
        _preflight_check(db)
        jobs = _build_jobs(subjects)
        import secrets

        def signature(blocks):
            return sorted(
                (
                    block["subject_id"], block["section_id"], block["room_id"],
                    block["day"], block["start"], block["end"], block["session_type"],
                )
                for block in blocks
            )

        previous = sorted(
            tuple(row)
            for row in db.execute(
                "SELECT subject_id, section_id, room_id, day, start, end, session_type FROM schedules"
            )
        )
        # Every click gets a fresh seed so repeated Generate presses produce a
        # different schedule instead of replaying the same placement.
        base_seed = secrets.randbits(32)
        placed = None
        failed_job = None
        for attempt in range(40):
            candidate, failed_job = _place_jobs(
                jobs, days, starts, rooms, online_room["id"], base_seed + attempt
            )
            if candidate is None:
                continue
            placed = candidate
            if signature(candidate) != previous:
                break
        if placed is None:
            placed = _min_conflicts_repair(
                jobs, days, rooms, online_room["id"], seed=base_seed
            )
        if placed is None:
            raise ValueError(
                f"Could not place {failed_job['code']} with a room, faculty, section, or break-time constraint. "
                "The data is too dense for the 5h/day and 2-session limits with the available rooms. "
                "Set more subjects to Online or reduce assignments and try again."
            )
        db.execute("DELETE FROM schedules")
        db.executemany(
            "INSERT INTO schedules(subject_id, section_id, faculty_id, room_id, day, start, end, session_type) "
            "VALUES (:subject_id, :section_id, :faculty_id, :room_id, :day, :start, :end, :session_type)",
            placed,
        )
        db.commit()
        return len(placed)


def register_user(first_name, last_name, username, email, role, password):
    from werkzeug.security import generate_password_hash

    values = (first_name.strip(), last_name.strip(), username.strip(), email.strip().lower(), role)
    if not all(values[:4]) or role != "dean" or len(password) < 8:
        raise ValueError("Complete all account fields and use a password with at least 8 characters.")
    with closing(connect()) as db:
        try:
            cursor = db.execute(
                "INSERT INTO users(first_name, last_name, username, email, role, password_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (*values, generate_password_hash(password)),
            )
            db.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise ValueError("That username or email is already registered.") from error


def get_user(user_id):
    """Return the account for a session user_id, or None if it no longer exists."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    with closing(connect()) as db:
        row = db.execute(
            "SELECT id, first_name, last_name, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def authenticate_user(identity, password):
    from werkzeug.security import check_password_hash

    with closing(connect()) as db:
        user = db.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?", (identity.strip(), identity.strip())
        ).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        return dict(user)
    return None
