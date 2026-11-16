from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for

from backend.app.routes.export_helpers import handle_export_request
from backend.app.services import backup_service, import_service, schedule_service as svc
from backend.app.services.import_service import XLSX_MIMETYPE

bp = Blueprint("dean", __name__)


@bp.before_request
def require_dean():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))
    user = svc.get_user(session["user_id"])
    if not user or user["role"] != "dean":
        session.clear()
        return redirect(url_for("auth.login"))


@bp.route("/")
def dashboard():
    return master_schedule()


@bp.route("/master-schedule")
def master_schedule():
    instructor = request.args.get("instructor", "").strip()
    section = request.args.get("section", "").strip()
    room = request.args.get("room", "").strip()
    return render_template(
        "dean_master_schedule.html",
        stats=svc.get_stats(instructor or None, section or None, room or None),
        weekly=svc.get_weekly_schedule(instructor=instructor or None, section=section or None, room=room or None),
        schedules=svc.get_schedules(instructor or None, section or None, room or None),
        subjects=svc.get_subjects(),
        sections=svc.get_sections(),
        all_rooms=svc.get_rooms(include_online=True),
        instructor=instructor,
        section_filter=section,
        room_filter=room,
        instructors=svc.get_instructor_surnames(),
        fill=bool(instructor or section or room),
        days=current_app.config["DAYS"],
        **svc.time_options(),
    )


@bp.route("/faculty", methods=["GET", "POST"])
def faculty():
    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action == "add_faculty":
                svc.add_faculty(request.form.get("name", ""))
                flash("Faculty member added.", "success")
            elif action == "remove_faculty":
                removed_subjects = svc.remove_faculty(request.form.get("faculty_id"))
                flash(
                    f"Faculty member removed with {removed_subjects} assigned subject(s) and their schedule blocks.",
                    "success",
                )
            elif action == "update_subject":
                removed_blocks = svc.update_subject(
                    request.form.get("subject_id"), request.form.get("faculty_id"),
                    request.form.get("code", ""), request.form.get("title", ""),
                    request.form.get("units"), request.form.get("room_type"),
                    request.form.get("delivery"), request.form.get("room_id"),
                )
                message = "Subject updated."
                if removed_blocks:
                    message += f" {removed_blocks} existing schedule block(s) were removed; regenerate the schedule."
                flash(message, "success")
            elif action == "remove_subject":
                removed_blocks = svc.remove_subject(request.form.get("subject_id"))
                flash(f"Subject removed with {removed_blocks} scheduled block(s).", "success")
            else:
                svc.add_subject(
                    request.form.get("faculty_id"), request.form.get("code", ""),
                    request.form.get("title", ""), request.form.get("units"),
                    request.form.get("room_type"), request.form.get("delivery", "In-person"),
                    request.form.get("room_id"),
                )
                flash("Subject assigned to faculty member.", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("dean.faculty"))
    instructors = svc.get_faculty()
    return render_template(
        "dean_faculty.html", instructors=instructors, all_faculty=instructors,
        all_rooms=svc.get_rooms(),
    )


@bp.route("/sections", methods=["GET", "POST"])
def sections():
    if request.method == "POST":
        try:
            if request.form.get("action") == "add_section":
                svc.add_section(
                    request.form.get("name", ""), request.form.get("year"),
                    request.form.get("program"),
                )
                flash("Section added.", "success")
            else:
                svc.add_subject_to_section(request.form.get("section_id"), request.form.get("subject_id"))
                flash("Subject added to section.", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("dean.sections"))
    return render_template(
        "dean_sections.html", sections=svc.get_sections(), subjects=svc.get_subjects()
    )


@bp.route("/rooms", methods=["GET", "POST"])
def rooms():
    if request.method == "POST":
        try:
            svc.add_room(
                request.form.get("name", ""), request.form.get("type"),
                request.form.get("seats"),
            )
            flash("Room added.", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(url_for("dean.rooms"))
    return render_template("rooms_labs.html", rooms=svc.get_rooms(), can_manage=True)


@bp.post("/generate")
def generate():
    try:
        count = svc.generate_schedule()
        flash(f"Generated {count} conflict-free schedule blocks.", "success")
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("dean.master_schedule"))


@bp.post("/schedule/<int:schedule_id>")
def edit_schedule(schedule_id):
    try:
        svc.save_schedule(
            request.form.get("subject_id"), request.form.get("section_id"),
            request.form.get("room_id"), request.form.get("day"),
            request.form.get("start"), request.form.get("end"),
            request.form.get("session_type"), schedule_id,
        )
        flash("Schedule updated.", "success")
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("dean.master_schedule"))


@bp.route("/import", methods=["GET", "POST"])
def import_page():
    results = None
    selected_kind = "faculty"
    if request.method == "POST":
        selected_kind = (request.form.get("kind") or "").strip().lower()
        upload = request.files.get("file")
        try:
            if selected_kind not in import_service.KINDS:
                raise ValueError("Choose what to import: faculty, sections, or rooms.")
            if upload is None or not upload.filename:
                raise ValueError("Choose an .xlsx file to upload.")
            results = import_service.import_xlsx(selected_kind, upload)
            if results["errors"]:
                flash(
                    f"Imported {results['imported']} {selected_kind}; "
                    f"{results['skipped']} duplicate(s) skipped; {len(results['errors'])} row error(s).",
                    "error",
                )
            else:
                flash(
                    f"Imported {results['imported']} {selected_kind}; "
                    f"{results['skipped']} duplicate(s) skipped.",
                    "success",
                )
        except ValueError as error:
            flash(str(error), "error")
    return render_template("import.html", results=results, selected_kind=selected_kind)


@bp.route("/import/template/<kind>")
def import_template(kind):
    try:
        buffer, filename = import_service.build_template(kind)
    except ValueError:
        abort(404)
    return send_file(buffer, mimetype=XLSX_MIMETYPE, as_attachment=True, download_name=filename)


@bp.route("/export", methods=["GET", "POST"])
def export():
    return handle_export_request()


@bp.route("/settings")
def settings():
    return render_template("dean_settings.html")


@bp.route("/settings/backup")
def backup_download():
    buffer, filename = backup_service.build_backup()
    return send_file(buffer, mimetype=XLSX_MIMETYPE, as_attachment=True, download_name=filename)


@bp.route("/settings/restore", methods=["POST"])
def backup_restore():
    upload = request.files.get("file")
    try:
        if upload is None or not upload.filename:
            raise ValueError("Choose a .xlsx backup file to upload.")
        counts = backup_service.restore_backup(upload)
        flash(
            "Backup restored: "
            f"{counts['rooms']} rooms, {counts['faculty']} faculty, {counts['subjects']} subjects, "
            f"{counts['sections']} sections, {counts['schedule']} schedule blocks.",
            "success",
        )
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("dean.settings"))


@bp.route("/settings/delete-schedule", methods=["POST"])
def delete_schedule():
    backup_service.delete_schedule()
    flash("Schedule cleared. All other data was kept.", "success")
    return redirect(url_for("dean.settings"))
