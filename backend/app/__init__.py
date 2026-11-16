from pathlib import Path
import os

from flask import Flask

from backend.config import Config


def create_app(test_config=None) -> Flask:
    """Create and configure the Flask application."""
    project_root = Path(__file__).resolve().parents[2]
    app = Flask(
        __name__,
        template_folder=str(project_root / "frontend" / "templates"),
        static_folder=str(project_root / "frontend" / "static"),
    )
    app.config.from_object(Config)
    app.config.update(test_config or {})
    database_path = Path(
        app.config.get("DATABASE")
        or os.getenv("CCSYNC_DATABASE", project_root / "instance" / "ccsync.sqlite3")
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    app.config["DATABASE"] = str(database_path)

    from backend.app.services.schedule_service import initialize_database

    with app.app_context():
        initialize_database()

    from backend.app.routes.auth import bp as auth_bp
    from backend.app.routes.dean import bp as dean_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dean_bp, url_prefix="/dean")
    return app
