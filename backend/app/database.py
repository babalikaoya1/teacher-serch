import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./teacher_search.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def ensure_schema(bind=engine):
    Base.metadata.create_all(bind=bind)
    inspector = inspect(bind)
    if not inspector.has_table("tutoring_jobs"):
        return
    existing_columns = {column["name"] for column in inspector.get_columns("tutoring_jobs")}
    additive_columns = {
        "owner_id": "INTEGER",
        "source_message_id": "INTEGER",
        "source_part": "INTEGER",
        "published_at": "DATETIME",
        "gender": "VARCHAR(12)",
        "city": "VARCHAR(80)",
        "teaching_mode": "VARCHAR(20)",
        "salary_basis": "VARCHAR(20)",
        "salary_is_minimum": "BOOLEAN NOT NULL DEFAULT FALSE",
        "order_code": "VARCHAR(80)",
        "student_notes": "TEXT",
        "requirements": "TEXT",
        "location_lat": "FLOAT",
        "location_lng": "FLOAT",
        "geocode_status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
        "geocode_error": "VARCHAR(240)",
        "geocode_attempted_at": "DATETIME",
    }
    missing = [(name, definition) for name, definition in additive_columns.items() if name not in existing_columns]
    if missing:
        with bind.begin() as connection:
            for name, definition in missing:
                if bind.dialect.name == "postgresql":
                    definition = definition.replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
                connection.exec_driver_sql(f"ALTER TABLE tutoring_jobs ADD COLUMN {name} {definition}")
    with bind.begin() as connection:
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_tutoring_jobs_city_coordinates "
            "ON tutoring_jobs (city, location_lat, location_lng)"
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_jobs_owner ON tutoring_jobs (owner_id, status, created_at)")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_message_part ON tutoring_jobs (source_message_id, source_part)")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
