from flask import abort, render_template, request, send_file

from backend.app.services import export_service, schedule_service

PROGRAM_NAMES = {
    "BSCS": "Bachelor of Science in Computer Science",
    "BSIT": "Bachelor of Science in Information Technology",
}


def _collect_entities(instructor_ids, section_ids, room_ids):
    schedules = schedule_service.get_schedules()
    entities = []

    for instructor in schedule_service.get_faculty():
        if str(instructor["id"]) not in instructor_ids:
            continue
        events = [item for item in schedules if item["instructor"] == instructor["name"]]
        entities.append({"kind": "instructor", "name": instructor["name"], "events": events})

    for section in schedule_service.get_sections():
        if str(section["id"]) not in section_ids:
            continue
        events = [item for item in schedules if item["section"] == section["name"]]
        entities.append({
            "kind": "section",
            "name": section["name"],
            "program_name": PROGRAM_NAMES.get(section["program"], section["program"]),
            "year": section["year"],
            "section_letter": section["name"].split()[-1][-1],
            "show_nstp_note": int(section["year"]) == 1,
            "events": events,
        })

    for room in schedule_service.get_rooms():
        if str(room["id"]) not in room_ids:
            continue
        events = [item for item in schedules if item["room"] == room["name"]]
        entities.append({
            "kind": "room",
            "name": room["name"],
            "room_type": room["type"],
            "events": events,
        })

    entities.sort(key=lambda item: {"instructor": 0, "section": 1, "room": 2}[item["kind"]])
    return entities


def handle_export_request():
    """Render the export page or download the combined PDF."""
    if request.method == "POST":
        instructor_ids = set(request.form.getlist("instructor"))
        section_ids = set(request.form.getlist("section"))
        room_ids = set(request.form.getlist("room"))
        try:
            entities = _collect_entities(instructor_ids, section_ids, room_ids)
            output, mimetype, filename = export_service.create_export(
                entities, request.form.get("file_name", "")
            )
        except ValueError as error:
            abort(400, description=str(error))

        return send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )

    return render_template(
        "export.html",
        instructors=schedule_service.get_faculty(),
        sections=schedule_service.get_sections(),
        rooms=schedule_service.get_rooms(),
    )
