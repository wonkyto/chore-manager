from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from .audit import configure_audit_logger, resolve_audit_log_path
from .config import load_app_config, load_config
from .db import db
from .routes import bp

csrf = CSRFProtect()


def _load_or_create_secret_key(instance_path: Path) -> str:
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = instance_path / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key


def create_app(
    config_path: Path | None = None,
    db_url: str | None = None,
) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.secret_key = _load_or_create_secret_key(Path(app.instance_path))

    cfg_path = config_path or Path(os.environ.get("CHORE_CONFIG", "config/family.yaml"))
    app.config["FAMILY"] = load_config(cfg_path)
    app.config["FAMILY_PATH"] = cfg_path

    app_cfg_path = cfg_path.parent / "app.yaml"
    app.config["APP_CONFIG_PATH"] = app_cfg_path
    app.config["TIMEZONE"] = load_app_config(app_cfg_path).timezone

    data_dir = Path(os.environ.get("CHORE_DATA_DIR", Path(app.instance_path)))
    data_dir.mkdir(parents=True, exist_ok=True)
    default_db = f"sqlite:///{data_dir / 'chore.db'}"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url or os.environ.get("CHORE_DB_URL", default_db)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    csrf.init_app(app)
    app.register_blueprint(bp)

    configure_audit_logger(resolve_audit_log_path())

    with app.app_context():
        _configure_sqlite(db.engine)
        db.create_all()
        _migrate(db)

    return app


def _configure_sqlite(engine) -> None:
    """Enable WAL and serialize writes to remove the redemption read-then-write race."""
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        # Hand transaction control to SQLAlchemy so the begin hook fires.
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def _migrate(db) -> None:
    """Add columns/tables that create_all won't add to existing databases."""
    migrations = [
        ("adhoc_chore", "start_date", "ALTER TABLE adhoc_chore ADD COLUMN start_date DATE"),
        ("adhoc_chore", "completed_date", "ALTER TABLE adhoc_chore ADD COLUMN completed_date DATE"),
        ("chore_skip", "created_at", "ALTER TABLE chore_skip ADD COLUMN created_at DATETIME"),
    ]
    with db.engine.connect() as conn:
        for table, column, sql in migrations:
            existing = {row[1] for row in conn.execute(db.text(f"PRAGMA table_info({table})"))}
            if column in existing:
                continue
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except OperationalError:
                conn.rollback()


def main() -> None:
    app = create_app()
    host = os.environ.get("CHORE_HOST", "0.0.0.0")
    port = int(os.environ.get("CHORE_PORT", "5000"))
    if os.environ.get("FLASK_DEBUG") == "1":
        app.run(host=host, port=port, debug=True)
        return
    from waitress import serve

    serve(app, host=host, port=port)


if __name__ == "__main__":
    main()
