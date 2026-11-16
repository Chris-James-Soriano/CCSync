import io
import re
import tempfile
import uuid
from pathlib import Path

import pytest

from backend.app import create_app


def create_client(role=None):
    database = Path(tempfile.gettempdir()) / f"ccsync-test-{uuid.uuid4().hex}.sqlite3"
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret", "DATABASE": str(database)})
    client = app.test_client()
    if role:
        assert role == "dean"
        sign_up(client)
    return client


def sign_up(client, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return client.post(
        "/signup",
        data={
            "first_name": "Test",
            "last_name": "Dean",
            "username": f"dean-{suffix}",
            "email": f"dean-{suffix}@example.com",
            "password": "StrongPass123",
            "confirm_password": "StrongPass123",
        },
    )


def test_pages_load():
    c = create_client("dean")
    dean_urls = [
        "/login",
        "/signup",
        "/more-information",
        "/dean/master-schedule",
        "/dean/faculty",
        "/dean/sections",
        "/dean/rooms",
        "/dean/export",
        "/dean/import",
        "/dean/settings",
    ]
    for url in dean_urls:
        assert c.get(url).status_code == 200, url


def test_signup_shows_requested_fields_in_order():
    response = create_client().get("/signup")
    assert response.status_code == 200
    fields = [
        b'name="first_name"',
        b'name="last_name"',
        b'name="username"',
        b'name="email"',
        b'name="password"',
        b'name="confirm_password"',
    ]
    positions = [response.data.index(field) for field in fields]
    assert positions == sorted(positions)
    assert b'name="role"' not in response.data
    assert b'<button class="btn signup-submit" type="submit">Sign Up</button>' in response.data
    for field in fields:
        field_markup = response.data.split(field, 1)[1].split(b">", 1)[0]
        assert b"required" not in field_markup


def test_signup_redirects_to_dean_dashboard_without_other_fields():
    client = create_client()
    sign_up(client, "account-test")
    response = client.get("/dean/", follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == "/dean/"
    assert b"Master Schedule" in response.data
    with client.session_transaction() as session:
        assert session["role"] == "dean"


def test_signup_ignores_any_posted_role_and_always_creates_dean():
    client = create_client()
    response = client.post("/signup", data={
        "first_name": "Test",
        "last_name": "Dean",
        "username": "dean-no-role",
        "email": "dean-no-role@example.com",
        "role": "admin",
        "password": "StrongPass123",
        "confirm_password": "StrongPass123",
    })
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["role"] == "dean"


def test_login_page_has_kamusta_and_login_form():
    response = create_client().get("/login")
    assert response.status_code == 200
    assert b'class="signup-welcome">KAMUSTA</span>' in response.data
    assert b'name="email"' in response.data
    assert b'type="text" name="email" placeholder="Enter your email or username"' in response.data
    assert b'name="password"' in response.data
    assert b'name="role"' not in response.data
    assert b'action="/signup"' not in response.data
    assert b'href="/signup"' in response.data


def test_auth_page_showcase_uses_available_system_screenshots():
    client = create_client()
    response = client.get("/signup")
    assert response.status_code == 200
    for label in (b"Dean master schedule", b"Schedule creation", b"Schedule exporting"):
        assert label in response.data

    image_urls = re.findall(rb'<img src="([^"]+)"', response.data)
    assert len(image_urls) >= 3
    for image_url in image_urls[:3]:
        assert client.get(image_url.decode()).status_code == 200


def test_export_pages_show_scoped_timetable_exports():
    c = create_client("dean")
    response = c.get("/dean/export")
    assert b'name="instructor"' in response.data
    assert b'name="section"' in response.data
    assert b'name="room"' in response.data
    assert b"Instructors" in response.data
    assert b"Sections" in response.data
    assert b"Rooms" in response.data
    assert b'name="format"' not in response.data
    assert b'name="schedules"' not in response.data


def test_export_downloads_pdf_for_each_scope():
    c = create_client("dean")
    for payload in ({"instructor": ["1"]}, {"section": ["1"]}, {"room": ["1"]}):
        response = c.post(
            "/dean/export",
            data=payload,
        )
        assert response.status_code == 200
        assert response.headers["Content-Disposition"].startswith("attachment;")
        assert response.data.startswith(b"%PDF-")


def test_export_requires_at_least_one_entity():
    c = create_client("dean")
    assert c.post("/dean/export", data={}).status_code == 400


def test_export_page_lists_all_groups_and_everything_starts_unchecked():
    c = create_client("dean")
    response = c.get("/dean/export")
    assert response.status_code == 200
    for group in (b"Instructors", b"Sections", b"Rooms"):
        assert group in response.data
    assert b"Export PDF" in response.data
    assert b"checked" not in response.data


def test_sidebar_uses_account_name_without_search_or_profile_edit_controls():
    c = create_client("dean")
    page = c.get("/dean/master-schedule")
    assert b"Test Dean" in page.data
    assert b"CCS Dean" in page.data
    assert b"Edit Profile" not in page.data
    sidebar = page.data.split(b'<nav class="sidebar">', 1)[1].split(b"</nav>", 1)[0]
    assert b'type="search"' not in sidebar
    assert c.get("/profile").status_code == 404


def test_dean_sidebar_displays_dean_profile_mockup():
    c = create_client("dean")
    page = c.get("/dean/master-schedule")
    assert page.status_code == 200
    assert b"Test Dean" in page.data
    assert b"CCS Dean" in page.data


def test_static_assets_are_served_from_frontend_static_directory():
    c = create_client()
    assert c.get("/static/css/main.css").status_code == 200
    assert c.get("/static/js/export.js").status_code == 200


def test_weekly_schedule_grid_has_seven_days_and_half_hour_labels():
    response = create_client("dean").get("/dean/master-schedule")
    assert response.status_code == 200
    assert response.data.count(b'class="week-time-label"') == 20
    for day in (b"MON", b"TUE", b"WED", b"THU", b"FRI", b"SAT", b"SUN"):
        assert day in response.data
    assert b"7:00 AM" in response.data
    assert b"4:30 PM" in response.data
    assert b"5:00 PM" in response.data
    assert b"Approvals" not in response.data
    assert create_client("dean").get("/dean/approvals").status_code == 404


def test_nstp_is_sunday_only_for_first_year_and_has_no_room_or_faculty():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    with client.application.app_context():
        schedules = svc.get_schedules()
        sections = {section["id"]: section for section in svc.get_sections()}
    nstp = [item for item in schedules if item.get("is_nstp")]
    assert nstp
    assert all(item["day"] == "SUN" and item["start"] == 7 and item["end"] == 17 for item in nstp)
    assert all(sections[item["section_id"]]["year"] == 1 for item in nstp)
    assert all(not item["faculty_id"] and not item["room_id"] for item in nstp)
    assert not [item for item in schedules if item["day"] == "SUN" and not item.get("is_nstp")]


def test_online_subjects_render_online_in_master_schedule_and_sections():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    with client.application.app_context():
        section = next(item for item in svc.get_sections() if item["name"] == "BSCS 4A")
        faculty = svc.get_faculty()[0]
        subject_id = svc.add_subject(faculty["id"], "ONL 401", "Online Systems", 3, "Lecture", "Online")
        svc.add_subject_to_section(section["id"], subject_id)
        svc.save_schedule(subject_id, section["id"], None, "MON", 7, 10)
    weekly = client.get("/dean/master-schedule")
    assert b"ONL 401" in weekly.data
    assert b"Online" in weekly.data
    section_page = client.get("/dean/sections")
    assert section_page.status_code == 200
    assert b"BSCS 4A" in section_page.data
    assert b"ONL 401" in section_page.data


def test_generated_schedule_spreads_section_blocks_with_breaks_before_five():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/generate")
    with client.application.app_context():
        schedules = [item for item in svc.get_schedules() if not item.get("is_nstp")]
    assert schedules and all(item["day"] != "SUN" and item["end"] <= 17 for item in schedules)
    section_days = {}
    for item in schedules:
        section_days.setdefault((item["section_id"], item["day"]), []).append(item)
    for blocks in section_days.values():
        assert len(blocks) <= 2
        assert sum(item["end"] - item["start"] for item in blocks) <= 5
        blocks.sort(key=lambda item: item["start"])
        assert all(left["end"] + 1 <= right["start"] for left, right in zip(blocks, blocks[1:]))


def test_generate_produces_a_new_schedule_on_each_click():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")

    def signature():
        with client.application.app_context():
            return sorted(
                (item["subject_id"], item["section_id"], item["room_id"], item["day"], item["start"], item["end"])
                for item in svc.get_schedules()
                if not item.get("is_nstp")
            )

    assert client.post("/dean/generate").status_code == 302
    first = signature()
    assert client.post("/dean/generate").status_code == 302
    second = signature()
    assert first and second
    assert first != second


def test_fixed_room_subject_is_generated_only_in_that_room():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    with client.application.app_context():
        fixed_room = next(room for room in svc.get_rooms() if room["name"] == "Room 103")
        faculty = svc.get_faculty()[0]
        subject_id = svc.add_subject(
            faculty["id"], "PIN 101", "Pinned Subject", 2, "Lecture", "In-person", fixed_room["id"]
        )
        section = next(item for item in svc.get_sections() if item["name"] == "BSCS 2A")
        svc.add_subject_to_section(section["id"], subject_id)

    assert client.post("/dean/generate").status_code == 302
    with client.application.app_context():
        blocks = [item for item in svc.get_schedules() if item.get("course") == "PIN 101"]
    assert blocks
    assert {item["room"] for item in blocks} == {fixed_room["name"]}


def test_fixed_room_rejects_scheduling_in_another_room():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    with client.application.app_context():
        lecture_rooms = [room for room in svc.get_rooms() if room["type"] == "Lecture"]
        fixed_room, other_room = lecture_rooms[0], lecture_rooms[1]
        faculty = svc.get_faculty()[0]
        subject_id = svc.add_subject(
            faculty["id"], "PIN 102", "Pinned Subject", 2, "Lecture", "In-person", fixed_room["id"]
        )
        section = next(item for item in svc.get_sections() if item["name"] == "BSCS 2A")
        svc.add_subject_to_section(section["id"], subject_id)
        with pytest.raises(ValueError, match="must be scheduled in"):
            svc.save_schedule(subject_id, section["id"], other_room["id"], "MON", 7, 9)


def test_accounts_authenticate_and_dean_routes_are_protected():
    client = create_client()
    assert client.get("/dean/master-schedule").status_code == 302
    assert sign_up(client, "account-test").status_code == 302
    assert client.get("/dean/master-schedule").status_code == 200
    assert client.get("/secretary/schedule").status_code == 404
    client.get("/logout")
    assert client.post("/login", data={"email": "dean-account-test", "password": "wrong-pass"}).status_code == 401
    assert client.post("/login", data={"email": "dean-account-test", "password": "StrongPass123"}).status_code == 302


def test_dean_can_add_faculty_subjects_and_generate_a_schedule():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/faculty", data={"action": "add_faculty", "name": "Jordan Sample"})
    with client.application.app_context():
        faculty = next(item for item in svc.get_faculty() if item["name"] == "Jordan Sample")
        subject_id = svc.add_subject(faculty["id"], "TEST 201", "Schedule Test", 3, "Lecture")
        section = next(item for item in svc.get_sections() if item["name"] == "BSCS 1A")
    assigned = client.post("/dean/sections", data={"section_id": section["id"], "subject_id": subject_id})
    assert assigned.status_code == 302
    assert client.post("/dean/generate").status_code == 302
    page = client.get("/dean/master-schedule", follow_redirects=True)
    assert b"Generated" in page.data
    assert b"schedule-row" in page.data


def test_manual_booking_conflicts_are_rejected():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    with client.application.app_context():
        section = next(item for item in svc.get_sections() if item["name"] == "BSCS 1A")
        lecture_room = next(room for room in svc.get_rooms() if room["type"] == "Lecture")
        subject_id = section["subjects"][0]["id"]
        overlapping_subject_id = section["subjects"][1]["id"]
        svc.save_schedule(subject_id, section["id"], lecture_room["id"], "MON", 7, 10)
        with pytest.raises(ValueError):
            svc.save_schedule(overlapping_subject_id, section["id"], lecture_room["id"], "MON", 8, 10)


def test_faculty_can_edit_reassign_remove_subjects_and_remove_faculty():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/faculty", data={"action": "add_faculty", "name": "Faculty One"})
    client.post("/dean/faculty", data={"action": "add_faculty", "name": "Faculty Two"})
    with client.application.app_context():
        faculty = {item["name"]: item["id"] for item in svc.get_faculty() if item["name"].startswith("Faculty ")}
        section = next(item for item in svc.get_sections() if item["name"] == "BSCS 1A")
        room_id = next(room["id"] for room in svc.get_rooms() if room["type"] == "Lecture")
        subject_id = svc.add_subject(faculty["Faculty One"], "EDIT 101", "Editable Subject", 2, "Lecture")
        svc.add_subject_to_section(section["id"], subject_id)
        svc.save_schedule(subject_id, section["id"], room_id, "MON", 7, 9)

    updated = client.post("/dean/faculty", data={
        "action": "update_subject", "subject_id": subject_id,
        "faculty_id": faculty["Faculty Two"], "code": "EDIT 201",
        "title": "Updated Subject", "units": "3", "room_type": "Lecture",
        "delivery": "In-person",
    }, follow_redirects=True)
    assert b"existing schedule block(s) were removed" in updated.data
    with client.application.app_context():
        edited = next(item for item in svc.get_subjects() if item["id"] == subject_id)
        assert edited["faculty_name"] == "Faculty Two"
        assert not any(item["subject_id"] == subject_id for item in svc.get_schedules())

    removed_subject = client.post("/dean/faculty", data={
        "action": "remove_subject", "subject_id": subject_id,
    })
    assert removed_subject.status_code == 302
    with client.application.app_context():
        assert not any(item["id"] == subject_id for item in svc.get_subjects())
        remaining_subject = svc.add_subject(faculty["Faculty Two"], "EDIT 202", "Faculty Two Subject", 2, "Lecture")
        svc.add_subject_to_section(section["id"], remaining_subject)
        svc.save_schedule(remaining_subject, section["id"], room_id, "MON", 7, 9)

    removed_faculty = client.post("/dean/faculty", data={
        "action": "remove_faculty", "faculty_id": faculty["Faculty Two"],
    }, follow_redirects=True)
    assert b"Faculty member removed" in removed_faculty.data
    with client.application.app_context():
        assert not any(item["id"] == faculty["Faculty Two"] for item in svc.get_faculty())
        assert not any(item["code"] == "EDIT 202" for item in svc.get_subjects())
        assert not any(item["course"] == "EDIT 202" for item in svc.get_schedules())


def test_faculty_weekly_load_is_the_sum_of_assigned_subject_units():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/faculty", data={"action": "add_faculty", "name": "Units Load Test"})
    with client.application.app_context():
        faculty = next(item for item in svc.get_faculty() if item["name"] == "Units Load Test")
        svc.add_subject(faculty["id"], "LOAD 201", "Three Units", 3, "Lecture")
        svc.add_subject(faculty["id"], "LOAD 202", "Two Units", 2, "Laboratory")
        load = next(item["weekly_hours"] for item in svc.get_faculty() if item["id"] == faculty["id"])
    assert load == 5

    page = client.get("/dean/faculty")
    assert b"5 / 40 hrs" in page.data


def build_xlsx(headers, rows):
    import io

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def test_dean_import_page_and_xlsx_templates_load():
    client = create_client("dean")
    assert client.get("/dean/import").status_code == 200
    for kind in ("faculty", "sections", "rooms"):
        response = client.get(f"/dean/import/template/{kind}")
        assert response.status_code == 200
        assert response.data[:2] == b"PK"  # .xlsx is a zip container
        assert "template" in response.headers["Content-Disposition"]
    assert client.get("/dean/import/template/bogus").status_code == 404


def test_dean_import_requires_login():
    client = create_client()
    response = client.get("/dean/import")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dean_import_faculty_sections_rooms_and_skips_duplicates():
    client = create_client("dean")

    rooms = build_xlsx(
        ["Name", "Type", "Seats"],
        [["Import Test Room", "Lecture", 50], ["TESOL", "Lecture", 40], ["Broken Room", "Basement", 10]],
    )
    response = client.post(
        "/dean/import",
        data={"kind": "rooms", "file": (rooms, "rooms.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"Import Test Room" not in response.data  # results list shows counts, not names of imports
    assert b"Imported 1 rooms" in response.data
    assert b"1 duplicate(s) skipped" in response.data
    assert b"1 row error(s)" in response.data

    sections = build_xlsx(
        ["Name", "Year", "Program"],
        [["BSCS 4B", 4, "BSCS"], ["BSCS 1A", 1, "BSCS"]],
    )
    response = client.post(
        "/dean/import",
        data={"kind": "sections", "file": (sections, "sections.xlsx")},
        content_type="multipart/form-data",
    )
    assert b"Imported 1 sections" in response.data
    assert b"1 duplicate(s) skipped" in response.data

    faculty = build_xlsx(["Name", "Status", "Weekly Capacity"], [["Import Test Faculty", "Active", 30]])
    response = client.post(
        "/dean/import",
        data={"kind": "faculty", "file": (faculty, "faculty.xlsx")},
        content_type="multipart/form-data",
    )
    assert b"Imported 1 faculty" in response.data

    with client.application.app_context():
        from backend.app.services import schedule_service as svc

        assert any(room["name"] == "Import Test Room" for room in svc.get_rooms())
        assert any(section["name"] == "BSCS 4B" for section in svc.get_sections())
        assert any(person["name"] == "Import Test Faculty" for person in svc.get_faculty())


def test_dean_import_faculty_with_embedded_subjects():
    client = create_client("dean")
    with client.application.app_context():
        from backend.app.services import schedule_service as svc

        svc.add_room("Import Subject Lab", "Laboratory", 30)

    faculty = build_xlsx(
        ["Name", "Status", "Weekly Capacity",
         "Subject Code", "Subject Title", "Units", "Room Type", "Delivery", "Fixed Room"],
        [
            ["Import Subject Faculty", "Active", 40, "ISF 101", "Imported Machines", 3, "Lecture", "In-person", ""],
            ["Import Subject Faculty", "Active", 40, "ISF 102", "Imported Labs", 3, "Laboratory", "In-person", "Import Subject Lab"],
            ["Import Subject Faculty", "Active", 40],
            ["Import Subject Faculty", "Active", 40, "ISF 103", "Broken Units", 4, "Lecture", "In-person", ""],
            ["Import Subject Faculty", "Active", 40, "CMSC 101", "Duplicate Code", 2, "Lecture", "In-person", ""],
        ],
    )
    response = client.post(
        "/dean/import",
        data={"kind": "faculty", "file": (faculty, "faculty.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"Embedded subjects" in response.data
    assert b"Row 5: Units must be 2, 3, or 5." in response.data
    assert b"Row 6: subject CMSC 101 already exists." in response.data

    with client.application.app_context():
        from backend.app.services import schedule_service as svc

        person = next(p for p in svc.get_faculty() if p["name"] == "Import Subject Faculty")
        subjects = {s["code"]: s for s in svc.get_subjects() if s["code"].startswith("ISF")}
        assert set(subjects) == {"ISF 101", "ISF 102"}
        assert all(s["faculty_id"] == person["id"] for s in subjects.values())
        assert subjects["ISF 102"]["fixed_room"] == "Import Subject Lab"
        assert subjects["ISF 101"]["fixed_room"] is None


def test_dean_import_faculty_with_subject_for_existing_faculty():
    client = create_client("dean")
    with client.application.app_context():
        from backend.app.services import schedule_service as svc

        faculty_id = svc.add_faculty("Existing Subject Owner")

    faculty = build_xlsx(
        ["Name", "Subject Code", "Subject Title", "Units", "Room Type", "Delivery"],
        [["Existing Subject Owner", "ESO 201", "Existing Owner Subject", 2, "Lecture", "In-person"]],
    )
    response = client.post(
        "/dean/import",
        data={"kind": "faculty", "file": (faculty, "faculty.xlsx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    with client.application.app_context():
        from backend.app.services import schedule_service as svc

        subjects = [s for s in svc.get_subjects() if s["code"] == "ESO 201"]
        assert subjects and subjects[0]["faculty_id"] == faculty_id


def test_dean_settings_page_and_sidebar_link():
    client = create_client("dean")
    page = client.get("/dean/settings")
    assert page.status_code == 200
    assert b"Master schedule" in page.data
    assert b"Import schedule" in page.data
    assert b"Import file" in page.data
    assert b">Import</button>" in page.data
    assert b"Delete schedule" in page.data
    master = client.get("/dean/master-schedule")
    assert b'href="/dean/settings"' in master.data
    assert b">Settings</span>" in master.data


def _schedule_signature(svc):
    return sorted(
        (item["course"], item["section"], item["day"], item["start"], item["end"],
         item.get("session_type"), item["room"], bool(item.get("is_nstp")))
        for item in svc.get_schedules()
    )


def test_settings_backup_roundtrip_restores_everything():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/generate")
    with client.application.app_context():
        before = _schedule_signature(svc)
        before_counts = {
            "rooms": len(svc.get_rooms()),
            "faculty": len(svc.get_faculty()),
            "subjects": len(svc.get_subjects()),
            "sections": len(svc.get_sections()),
        }

    response = client.get("/dean/settings/backup")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert response.data[:2] == b"PK"

    # Remove all data tables directly (equivalent of the removed factory reset),
    # then sign up a brand-new account in the same DB.
    import sqlite3

    db_path = client.application.config["DATABASE"]
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM schedules")
    conn.execute("DELETE FROM section_subjects")
    conn.execute("DELETE FROM subjects")
    conn.execute("DELETE FROM sections")
    conn.execute("DELETE FROM faculty")
    conn.execute("DELETE FROM rooms WHERE lower(name) != 'online'")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    with client.application.app_context():
        assert svc.get_faculty() == [] and svc.get_sections() == [] and svc.get_schedules() == []

    sign_up(client, "after-wipe")
    restore = client.post(
        "/dean/settings/restore",
        data={"file": (io.BytesIO(response.data), "ccsync-backup.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert restore.status_code == 200
    assert b"Backup restored" in restore.data
    with client.application.app_context():
        assert _schedule_signature(svc) == before
        assert len(svc.get_rooms()) == before_counts["rooms"]
        assert len(svc.get_faculty()) == before_counts["faculty"]
        assert len(svc.get_subjects()) == before_counts["subjects"]
        assert len(svc.get_sections()) == before_counts["sections"]


def test_settings_backup_restore_keeps_sessions_and_makes_nothing_else_up():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/generate")
    with client.application.app_context():
        before = _schedule_signature(svc)
    response = client.get("/dean/settings/backup")
    restore = client.post(
        "/dean/settings/restore",
        data={"file": (io.BytesIO(response.data), "backup.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Backup restored" in restore.data
    # Accounts are untouched, so the session is still valid.
    assert client.get("/dean/master-schedule").status_code == 200
    with client.application.app_context():
        assert _schedule_signature(svc) == before


def test_settings_restore_rejects_invalid_file_and_changes_nothing():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    with client.application.app_context():
        before_subjects = len(svc.get_subjects())
        before_schedule = len(svc.get_schedules())

    restore = client.post(
        "/dean/settings/restore",
        data={"file": (io.BytesIO(b"not an xlsx at all"), "backup.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"could not be read as an .xlsx" in restore.data
    with client.application.app_context():
        assert len(svc.get_subjects()) == before_subjects
        assert len(svc.get_schedules()) == before_schedule

    bad = build_xlsx(["Name", "Type", "Seats"], [["Nope", "Basement", 10]])
    restore = client.post(
        "/dean/settings/restore",
        data={"file": (bad, "backup.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"The backup is invalid" in restore.data
    with client.application.app_context():
        assert len(svc.get_subjects()) == before_subjects
        assert len(svc.get_schedules()) == before_schedule


def test_settings_delete_schedule_clears_only_the_schedule():
    import sqlite3

    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/generate")
    with client.application.app_context():
        before_sections = len(svc.get_sections())
        before_subjects = len(svc.get_subjects())
        before_faculty = len(svc.get_faculty())
        before_rooms = len(svc.get_rooms())
        assert svc.get_schedules()

    response = client.post("/dean/settings/delete-schedule", follow_redirects=True)
    assert response.status_code == 200
    assert b"Schedule cleared" in response.data
    with client.application.app_context():
        # Only synthetic NSTP blocks remain (they derive from first-year sections).
        assert [item for item in svc.get_schedules() if not item.get("is_nstp")] == []
        assert len(svc.get_sections()) == before_sections
        assert len(svc.get_subjects()) == before_subjects
        assert len(svc.get_faculty()) == before_faculty
        assert len(svc.get_rooms()) == before_rooms

    # The session stays valid and accounts are untouched.
    assert client.get("/dean/master-schedule").status_code == 200
    db_path = client.application.config["DATABASE"]
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
    conn.close()


def test_dean_import_rejects_non_xlsx_files():
    client = create_client("dean")
    import io

    response = client.post(
        "/dean/import",
        data={"kind": "rooms", "file": (io.BytesIO(b"name,type,seats"), "rooms.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"Only .xlsx files are accepted" in response.data

def test_dean_can_add_a_section_and_duplicates_are_rejected():
    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    response = client.post("/dean/sections", data={
        "action": "add_section", "name": "bscs 9z", "year": "4", "program": "bscs",
    })
    assert response.status_code == 302
    with client.application.app_context():
        assert any(section["name"] == "BSCS 9Z" for section in svc.get_sections())

    duplicate = client.post("/dean/sections", data={
        "action": "add_section", "name": "BSCS 9Z", "year": "4", "program": "BSCS",
    }, follow_redirects=True)
    assert b"That section already exists." in duplicate.data

    bad_year = client.post("/dean/sections", data={
        "action": "add_section", "name": "BSCS 8Y", "year": "9", "program": "BSCS",
    }, follow_redirects=True)
    assert b"Year must be 1, 2, 3, or 4." in bad_year.data

    bad_program = client.post("/dean/sections", data={
        "action": "add_section", "name": "BSCS 8X", "year": "1", "program": "BSIE",
    }, follow_redirects=True)
    assert b"Program must be BSCS or BSIT." in bad_program.data

    page = client.get("/dean/sections")
    assert page.status_code == 200
    assert b"BSCS 9Z" in page.data

def test_master_schedule_section_and_room_filters():
    from urllib.parse import quote

    from backend.app.services import schedule_service as svc

    client = create_client("dean")
    client.post("/dean/generate")
    with client.application.app_context():
        schedules = [item for item in svc.get_schedules() if not item.get("is_nstp")]
        section_name = schedules[0]["section"]
        room_name = next((item["room"] for item in schedules if item["room"] != "Online"), None)

        by_section = svc.get_schedules(section=section_name)
        assert by_section
        assert all(item["section"] == section_name for item in by_section)

        by_room = svc.get_schedules(room=room_name)
        assert by_room
        assert all(item["room"] == room_name for item in by_room)
        assert not any(item.get("is_nstp") for item in by_room)

        both = svc.get_schedules(section=section_name, room=room_name)
        assert all(item["section"] == section_name and item["room"] == room_name for item in both)

        section_stats = svc.get_stats(section=section_name)
        assert section_stats["classes"] == len(by_section)
        room_stats = svc.get_stats(room=room_name)
        assert room_stats["classes"] == len(by_room)

    section_page = client.get(f"/dean/master-schedule?section={quote(section_name)}")
    assert section_page.status_code == 200
    assert b'name="section"' in section_page.data
    assert b'name="room"' in section_page.data
    assert f'value="{section_name}" selected'.encode() in section_page.data

    room_page = client.get(f"/dean/master-schedule?room={quote(room_name)}")
    assert room_page.status_code == 200
    assert f'value="{room_name}" selected'.encode() in room_page.data
