"""
Idempotent migration helper for adding new columns / tables to existing databases.

Why this file? SQLAlchemy's `Base.metadata.create_all()` ONLY creates tables
that don't exist yet. It does NOT add new columns to existing tables.
So when we add new fields (phone_number, notify_email, etc.) to an existing
TwinFlow database, we need to ALTER TABLE manually.

This works on BOTH SQLite and PostgreSQL by inspecting the existing schema
first (SQLite doesn't support `ADD COLUMN IF NOT EXISTS`).
Safe to run on every startup.
"""
from sqlalchemy import inspect, text

from database import engine
from models import Badge, ScheduleTaskStatus


# (column_name, SQL type, default_clause_or_None)
USER_COLUMNS_TO_ADD = [
    ("phone_number",            "VARCHAR(20)", None),
    ("google_sub",              "VARCHAR(255)", None),
    ("telegram_chat_id",        "VARCHAR(64)", None),
    ("telegram_link_code",      "VARCHAR(8)",  None),
    ("profile_photo",           "TEXT",        None),
    ("notify_email",            "BOOLEAN",     "DEFAULT 1"),
    ("notify_sms",              "BOOLEAN",     "DEFAULT 1"),
    ("notify_telegram",         "BOOLEAN",     "DEFAULT 1"),
    ("last_weekly_report_sent", "TIMESTAMP",   None),
]

PRODUCTIVITY_COLUMNS_TO_ADD = [
    ("schedule_completion_pct", "FLOAT", None),
]


def run_migrations() -> None:
    """Add any new columns / tables to existing DB. Safe to run on every startup."""
    inspector = inspect(engine)

    if "users" not in inspector.get_table_names():
        # Fresh DB — create_all() will handle everything
        print("[db_migrate] Fresh DB detected; nothing to migrate.")
        return

    existing_cols = {c["name"] for c in inspector.get_columns("users")}
    productivity_cols = set()
    if "productivity_entries" in inspector.get_table_names():
        productivity_cols = {c["name"] for c in inspector.get_columns("productivity_entries")}
    added = []
    skipped = []

    with engine.begin() as conn:
        # 0. Create new tables added after the original project launch.
        if "badges" not in inspector.get_table_names():
            try:
                Badge.__table__.create(bind=conn)
                print("[db_migrate] Created badges table.")
            except Exception as e:
                print(f"[db_migrate] WARN failed to create badges table: {e}")
        if "schedule_task_statuses" not in inspector.get_table_names():
            try:
                ScheduleTaskStatus.__table__.create(bind=conn)
                print("[db_migrate] Created schedule_task_statuses table.")
            except Exception as e:
                print(f"[db_migrate] WARN failed to create schedule_task_statuses table: {e}")

        # 1. Add missing columns to `users`
        for col_name, col_type, default_clause in USER_COLUMNS_TO_ADD:
            if col_name in existing_cols:
                skipped.append(col_name)
                continue
            sql = f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"
            if default_clause:
                sql += f" {default_clause}"
            try:
                conn.execute(text(sql))
                added.append(col_name)
            except Exception as e:
                print(f"[db_migrate] WARN failed to add {col_name}: {e}")

        # 2. Add missing columns to `productivity_entries`
        for col_name, col_type, default_clause in PRODUCTIVITY_COLUMNS_TO_ADD:
            if col_name in productivity_cols:
                skipped.append(f"productivity_entries.{col_name}")
                continue
            sql = f"ALTER TABLE productivity_entries ADD COLUMN {col_name} {col_type}"
            if default_clause:
                sql += f" {default_clause}"
            try:
                conn.execute(text(sql))
                added.append(f"productivity_entries.{col_name}")
            except Exception as e:
                print(f"[db_migrate] WARN failed to add productivity_entries.{col_name}: {e}")

        # 3. Add helpful index on phone_number if missing.
        #    Both SQLite and PostgreSQL support `CREATE INDEX IF NOT EXISTS`.
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_users_phone_number "
                "ON users (phone_number)"
            ))
        except Exception as e:
            print(f"[db_migrate] WARN index create failed: {e}")
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub "
                "ON users (google_sub)"
            ))
        except Exception as e:
            print(f"[db_migrate] WARN google_sub index create failed: {e}")

    if added:
        print(f"[db_migrate] Added new columns: {', '.join(added)}")
    if skipped:
        print(f"[db_migrate] Already up-to-date: {', '.join(skipped)}")
    print("[db_migrate] Migrations applied.")
