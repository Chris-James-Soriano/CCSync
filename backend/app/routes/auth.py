from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from backend.app.services import schedule_service as svc

bp = Blueprint("auth", __name__)

ROLES = ("dean",)


@bp.route("/")
def index():
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = svc.authenticate_user(
            request.form.get("email", ""), request.form.get("password", "")
        )
        if not user:
            return render_template("login.html", error="Email, username, or password is incorrect."), 401
        session.clear()
        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["name"] = f"{user['first_name']} {user['last_name']}"
        return redirect(url_for("dean.dashboard"))
    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        role = "dean"
        password = request.form.get("password", "")
        if password != request.form.get("confirm_password", ""):
            return render_template("signup.html", error="Passwords do not match."), 400
        try:
            user_id = svc.register_user(
                request.form.get("first_name", ""), request.form.get("last_name", ""),
                request.form.get("username", ""), request.form.get("email", ""),
                role, password,
            )
        except ValueError as error:
            return render_template("signup.html", error=str(error)), 400
        session.clear()
        session["user_id"] = user_id
        session["role"] = role
        session["name"] = f"{request.form['first_name'].strip()} {request.form['last_name'].strip()}"
        return redirect(url_for("dean.dashboard"))

    return render_template("signup.html")


@bp.route("/more-information")
def more_information():
    return render_template("more_information.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
