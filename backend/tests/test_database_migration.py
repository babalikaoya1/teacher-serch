from sqlalchemy import create_engine, inspect, text

from app.database import ensure_schema


def test_existing_database_gets_additive_columns_without_losing_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old-schema.db'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE tutoring_jobs (
                id INTEGER NOT NULL PRIMARY KEY,
                subject VARCHAR(40),
                grade VARCHAR(40),
                location VARCHAR(120),
                salary FLOAT,
                salary_unit VARCHAR(20),
                schedule VARCHAR(120),
                raw_text TEXT NOT NULL,
                source_group VARCHAR(120),
                status VARCHAR(20),
                created_at DATETIME
            )
        """))
        connection.execute(text("INSERT INTO tutoring_jobs (id, subject, raw_text) VALUES (1, 'math', 'old order')"))

    ensure_schema(bind=engine)

    columns = {column["name"] for column in inspect(engine).get_columns("tutoring_jobs")}
    with engine.connect() as connection:
        old_job = connection.execute(text("SELECT id, raw_text, salary_is_minimum, geocode_status FROM tutoring_jobs WHERE id = 1")).one()
    engine.dispose()

    assert {"gender", "teaching_mode", "order_code", "location_lat", "location_lng"}.issubset(columns)
    assert old_job.raw_text == "old order"
    assert bool(old_job.salary_is_minimum) is False
    assert old_job.geocode_status == "pending"
